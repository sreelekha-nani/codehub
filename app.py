import os
import random
import string
import pandas as pd
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'

# --- Database Configuration ---
db_url = os.environ.get('DATABASE_URL')
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'codehub.db')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Helper Functions ---

def generate_random_password(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for i in range(length))

def get_next_student_id():
    last_student = User.query.filter(User.username.like('CH%')).order_by(User.id.desc()).first()
    if not last_student:
        return "CH001"
    try:
        last_id_num = int(last_student.username[2:])
        new_id_num = last_id_num + 1
        return f"CH{new_id_num:03d}"
    except ValueError:
        return "CH001"

# --- Database Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True) # Added email
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False) # 'admin' or 'student'

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    
    user = db.relationship('User', backref=db.backref('submissions', lazy=True))
    question = db.relationship('Question', backref=db.backref('submissions', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Initial Database Setup ---

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin_user = User(
            username='admin',
            email='admin@codehub.com',
            password=generate_password_hash('admin123'),
            role='admin'
        )
        db.session.add(admin_user)
        db.session.commit()

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard' if current_user.role == 'student' else 'admin_panel'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username, role='student').first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash(f'Welcome, {username}!', 'success')
            return redirect(url_for('dashboard'))
        
        flash('Invalid student username or password.', 'danger')
    return render_template('login.html')

@app.route('/adminlogin', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.role == 'admin':
        return redirect(url_for('admin_panel'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username, role='admin').first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Admin Login Successful!', 'success')
            return redirect(url_for('admin_panel'))
        
        flash('Invalid admin credentials.', 'danger')
    return render_template('admin_login.html')

@app.route('/admin')
@login_required
def admin_panel():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    questions = Question.query.all()
    students = User.query.filter_by(role='student').all()
    submissions = Submission.query.all()
    return render_template('admin.html', questions=questions, students=students, submissions=submissions)

@app.route('/admin/upload_students', methods=['POST'])
@login_required
def upload_students():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('admin_panel'))
    
    if file and file.filename.endswith('.xlsx'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            df = pd.read_excel(filepath)
            if 'email' not in df.columns:
                flash("Excel must contain an 'email' column.", 'danger')
                return redirect(url_for('admin_panel'))
            
            created_users = []
            for email in df['email']:
                email = str(email).strip()
                if not User.query.filter_by(email=email).first():
                    username = get_next_student_id()
                    password = generate_random_password()
                    new_user = User(
                        username=username,
                        email=email,
                        password=generate_password_hash(password),
                        role='student'
                    )
                    db.session.add(new_user)
                    db.session.commit()
                    created_users.append(f"{email} | User: {username} | Pass: {password}")
            
            if created_users:
                session['batch_credentials'] = created_users
                flash(f'Successfully created {len(created_users)} students!', 'success')
            else:
                flash('No new students were created (emails might already exist).', 'info')
                
        except Exception as e:
            flash(f"Error processing Excel: {str(e)}", 'danger')
        
        return redirect(url_for('admin_panel'))
    
    flash('Please upload a valid .xlsx file.', 'danger')
    return redirect(url_for('admin_panel'))

@app.route('/admin/edit_student/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_student(id):
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    student = User.query.get_or_404(id)
    if request.method == 'POST':
        student.username = request.form.get('username')
        student.email = request.form.get('email')
        new_password = request.form.get('password')
        if new_password:
            student.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Student updated successfully!', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('edit_student.html', student=student)

@app.route('/admin/delete_student/<int:id>')
@login_required
def delete_student(id):
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    student = User.query.get_or_404(id)
    # Delete related submissions first
    Submission.query.filter_by(user_id=student.id).delete()
    db.session.delete(student)
    db.session.commit()
    flash('Student deleted!', 'info')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_question', methods=['POST'])
@login_required
def add_question():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    new_q = Question(
        title=request.form.get('title'),
        description=request.form.get('description'),
        answer=request.form.get('answer')
    )
    db.session.add(new_q)
    db.session.commit()
    flash('Question added!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'student': return redirect(url_for('admin_panel'))
    questions = Question.query.all()
    user_submissions = {s.question_id: s for s in current_user.submissions}
    return render_template('dashboard.html', questions=questions, user_submissions=user_submissions)

@app.route('/submit/<int:question_id>', methods=['POST'])
@login_required
def submit_answer(question_id):
    if current_user.role != 'student': return redirect(url_for('admin_panel'))
    ans = request.form.get('answer')
    existing = Submission.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    if existing:
        existing.answer = ans
    else:
        db.session.add(Submission(user_id=current_user.id, question_id=question_id, answer=ans))
    db.session.commit()
    flash('Answer submitted!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/leaderboard')
@login_required
def leaderboard():
    from sqlalchemy import func
    rankings = db.session.query(User.username, func.count(Submission.id).label('score'))\
        .join(Submission, User.id == Submission.user_id, isouter=True)\
        .filter(User.role == 'student')\
        .group_by(User.id).order_by(db.desc('score')).all()
    return render_template('leaderboard.html', rankings=rankings)

if __name__ == '__main__':
    app.run(debug=True)
