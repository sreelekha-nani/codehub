import os
import random
import string
import pandas as pd
import logging
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# 7. LOGGING (MANDATORY)
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'render_deploy_secret_key_2024')

# 6. RENDER COMPATIBILITY (DATABASE_URL)
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = '/tmp'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# 1. DATABASE FIX (User Model)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)
    password = db.Column(db.Text, nullable=False) # STRICT REQUIREMENT: db.Text
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

# 2 & 3. SAFE DB INITIALIZATION & ADMIN CREATION
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            password=generate_password_hash("admin123"),
            role="admin"
        )
        db.session.add(admin)
        db.session.commit()
        logging.info("Admin user created successfully.")

# --- Helper Functions ---

def generate_random_password(length=8):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

def get_next_student_id():
    last = User.query.filter(User.username.like('CH%')).order_by(User.id.desc()).first()
    if not last: return "CH001"
    try:
        return f"CH{int(last.username[2:]) + 1:03d}"
    except: return "CH001"

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
            return redirect(url_for('dashboard'))
        flash('Invalid student credentials.', 'danger')
    return render_template('login.html')

# 5. LOGIN ROUTE FIX (/adminlogin)
@app.route('/adminlogin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        return render_template('admin_login.html')
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    try:
        user = User.query.filter_by(username=username).first()

        if not user:
            return "User not found"

        if not check_password_hash(user.password, password):
            return "Wrong password"

        login_user(user)
        return redirect(url_for("admin_panel"))

    except Exception as e:
        logging.error(f"Login Error: {str(e)}")
        return f"Error: {str(e)}"

@app.route('/admin')
@login_required
def admin_panel():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    return render_template('admin.html', 
                           questions=Question.query.all(), 
                           students=User.query.filter_by(role='student').all(), 
                           submissions=Submission.query.all())

@app.route('/admin/upload_students', methods=['POST'])
@login_required
def upload_students():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    file = request.files.get('file')
    if file and file.filename.endswith('.xlsx'):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
        file.save(filepath)
        try:
            df = pd.read_excel(filepath)
            created = []
            for email in df['email']:
                email = str(email).strip()
                if not User.query.filter_by(email=email).first():
                    username, password = get_next_student_id(), generate_random_password()
                    db.session.add(User(username=username, email=email, password=generate_password_hash(password), role='student'))
                    db.session.commit()
                    created.append(f"{email} | {username} | {password}")
            if created: session['batch_credentials'] = created
            flash(f'Batch processed: {len(created)} students enrolled.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error processing Excel: {str(e)}", 'danger')
    return redirect(url_for('admin_panel'))

@app.route('/admin/edit_student/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_student(id):
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    student = User.query.get_or_404(id)
    if request.method == 'POST':
        student.username, student.email = request.form.get('username'), request.form.get('email')
        if request.form.get('password'): 
            student.password = generate_password_hash(request.form.get('password'))
        db.session.commit()
        return redirect(url_for('admin_panel'))
    return render_template('edit_student.html', student=student)

@app.route('/admin/delete_student/<int:id>')
@login_required
def delete_student(id):
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    student = User.query.get_or_404(id)
    Submission.query.filter_by(user_id=student.id).delete()
    db.session.delete(student)
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_question', methods=['POST'])
@login_required
def add_question():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    db.session.add(Question(title=request.form.get('title'), description=request.form.get('description'), answer=request.form.get('answer')))
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'student': return redirect(url_for('admin_panel'))
    return render_template('dashboard.html', 
                           questions=Question.query.all(), 
                           user_submissions={s.question_id: s for s in current_user.submissions})

@app.route('/submit/<int:question_id>', methods=['POST'])
@login_required
def submit_answer(question_id):
    if current_user.role != 'student': return redirect(url_for('admin_panel'))
    existing = Submission.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    if existing: 
        existing.answer = request.form.get('answer')
    else: 
        db.session.add(Submission(user_id=current_user.id, question_id=question_id, answer=request.form.get('answer')))
    db.session.commit()
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
