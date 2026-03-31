import os
import random
import string
import pandas as pd
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_secret_key_998877')

# --- Production Database Configuration ---
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = '/tmp'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Database Models ---

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)
    password = db.Column(db.Text, nullable=False) # Changed to Text to avoid truncation
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
    try:
        return User.query.get(int(user_id))
    except:
        return None

# --- Safe Database & Admin Setup ---
def init_db():
    try:
        with app.app_context():
            db.create_all()
            # Check for existing admin to avoid duplicate key errors
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                new_admin = User(
                    username='admin',
                    email='admin@codehub.com',
                    password=generate_password_hash('admin123'),
                    role='admin'
                )
                db.session.add(new_admin)
                db.session.commit()
                print("Default admin created successfully.")
    except Exception as e:
        print(f"Database Init Warning: {e}")

init_db()

# --- Helper Functions ---

def generate_random_password(length=8):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

def get_next_student_id():
    try:
        last = User.query.filter(User.username.like('CH%')).order_by(User.id.desc()).first()
        if not last: return "CH001"
        return f"CH{int(last.username[2:]) + 1:03d}"
    except:
        return "CH001"

# --- Authentication Routes ---

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
            flash(f'Welcome back, {username}!', 'success')
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
            flash('Admin session started.', 'success')
            return redirect(url_for('admin_panel'))
        
        flash('Invalid admin credentials.', 'danger')
    return render_template('admin_login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Successfully logged out.', 'info')
    return redirect(url_for('login'))

# --- Admin Routes ---

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
        try:
            student.username, student.email = request.form.get('username'), request.form.get('email')
            if request.form.get('password'): 
                student.password = generate_password_hash(request.form.get('password'))
            db.session.commit()
            flash('Student profile updated.', 'success')
            return redirect(url_for('admin_panel'))
        except IntegrityError:
            db.session.rollback()
            flash('Username or Email already exists.', 'danger')
    return render_template('edit_student.html', student=student)

@app.route('/admin/delete_student/<int:id>')
@login_required
def delete_student(id):
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    student = User.query.get_or_404(id)
    try:
        Submission.query.filter_by(user_id=student.id).delete()
        db.session.delete(student)
        db.session.commit()
        flash('Student record deleted.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f"Deletion failed: {e}", 'danger')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_question', methods=['POST'])
@login_required
def add_question():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    try:
        db.session.add(Question(
            title=request.form.get('title'), 
            description=request.form.get('description'), 
            answer=request.form.get('answer')
        ))
        db.session.commit()
        flash('Challenge published.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to add question: {e}", 'danger')
    return redirect(url_for('admin_panel'))

# --- Student Routes ---

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
    try:
        existing = Submission.query.filter_by(user_id=current_user.id, question_id=question_id).first()
        if existing: 
            existing.answer = request.form.get('answer')
        else: 
            db.session.add(Submission(user_id=current_user.id, question_id=question_id, answer=request.form.get('answer')))
        db.session.commit()
        flash('Solution submitted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Submission failed: {e}", 'danger')
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
