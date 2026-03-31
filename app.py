import os
import random
import string
import pandas as pd
import subprocess
import json
from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# 1. Initialize Flask App
app = Flask(__name__)

# 2. Database Configuration (SQLite)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SECRET_KEY'] = 'dev_secret_key_12345'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'codehub.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 3. Initialize Extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Database Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)
    password = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(50), nullable=False) 

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    sample_input = db.Column(db.Text, nullable=True)
    sample_output = db.Column(db.Text, nullable=True)
    test_cases = db.Column(db.Text, nullable=True) 
    time_limit = db.Column(db.Integer, default=5) 

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    code = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(20), default='python')
    result = db.Column(db.String(100), nullable=True) 
    score = db.Column(db.Integer, default=0)
    
    user = db.relationship('User', backref=db.backref('submissions', lazy=True))
    question = db.relationship('Question', backref=db.backref('submissions', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Initial Database Setup ---
with app.app_context():
    # Force creation of tables with new columns
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

# --- Helper Functions ---

def generate_random_password(length=8):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

def get_next_student_id():
    last = User.query.filter(User.username.like('CH%')).order_by(User.id.desc()).first()
    if not last: return "CH001"
    try:
        return f"CH{int(last.username[2:]) + 1:03d}"
    except: return "CH001"

# --- Main Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin': return redirect(url_for('admin_panel'))
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username, password = request.form.get('username'), request.form.get('password')
        user = User.query.filter_by(username=username, role='student').first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'danger')
    return render_template('login.html')

@app.route('/adminlogin', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.role == 'admin':
        return redirect(url_for('admin_panel'))
    if request.method == 'POST':
        username, password = request.form.get('username'), request.form.get('password')
        user = User.query.filter_by(username=username, role='admin').first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin_panel'))
        flash('Invalid admin credentials.', 'danger')
    return render_template('admin_login.html')

@app.route('/admin')
@login_required
def admin_panel():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    return render_template('admin.html', questions=Question.query.all(), students=User.query.filter_by(role='student').all(), submissions=Submission.query.all())

# --- Admin Actions ---

@app.route('/add_question', methods=['POST'])
@login_required
def add_question():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    new_q = Question(
        title=request.form.get('title'),
        description=request.form.get('description'),
        sample_input=request.form.get('sample_input'),
        sample_output=request.form.get('sample_output'),
        test_cases=request.form.get('test_cases'),
        time_limit=request.form.get('time_limit', type=int)
    )
    db.session.add(new_q)
    db.session.commit()
    flash('Question added!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/upload_students', methods=['POST'])
@login_required
def upload_students():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    file = request.files.get('file')
    if file and file.filename.endswith('.xlsx'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        try:
            df = pd.read_excel(filepath)
            created = []
            for email in df['email']:
                email = str(email).strip()
                if not User.query.filter_by(email=email).first():
                    username = get_next_student_id()
                    plain_password = generate_random_password()
                    db.session.add(User(
                        username=username, 
                        email=email, 
                        password=generate_password_hash(plain_password), 
                        role='student'
                    ))
                    db.session.commit()
                    created.append(f"User: {username} | Email: {email} | Pass: {plain_password}")
            if created: session['batch_credentials'] = created
            flash(f'Batch processed: {len(created)} students enrolled.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {e}", 'danger')
    return redirect(url_for('admin_panel'))

@app.route('/edit_password/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_password(user_id):
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        pw = request.form.get('password')
        cpw = request.form.get('confirm_password')
        if pw == cpw:
            user.password = generate_password_hash(pw)
            db.session.commit()
            flash(f'Password updated for {user.username}', 'success')
            return redirect(url_for('admin_panel'))
        flash('Passwords do not match', 'danger')
    return render_template('edit_password.html', user=user)

@app.route('/edit_student/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_student(id):
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    student = User.query.get_or_404(id)
    if request.method == 'POST':
        student.username, student.email = request.form.get('username'), request.form.get('email')
        if request.form.get('password'): student.password = generate_password_hash(request.form.get('password'))
        db.session.commit()
        return redirect(url_for('admin_panel'))
    return render_template('edit_student.html', student=student)

@app.route('/delete_student/<int:id>')
@login_required
def delete_student(id):
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    Submission.query.filter_by(user_id=id).delete()
    db.session.delete(User.query.get(id))
    db.session.commit()
    return redirect(url_for('admin_panel'))

# --- Student Routes ---

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'student': return redirect(url_for('admin_panel'))
    questions = Question.query.all()
    user_submissions = {s.question_id: s for s in current_user.submissions}
    return render_template('dashboard.html', questions=questions, user_submissions=user_submissions)

@app.route('/solve/<int:qid>')
@login_required
def solve(qid):
    if current_user.role != 'student': return redirect(url_for('admin_panel'))
    question = Question.query.get_or_404(qid)
    return render_template('solve.html', question=question)

import tempfile

@app.route('/run_code', methods=['POST'])
@login_required
def run_code():
    try:
        data = request.get_json()
        code = data.get('code', '')
        user_input = data.get('input', '')

        # Use tempfile for safer execution
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
            f.write(code.encode())
            filename = f.name

        result = subprocess.run(
            ["python", filename],
            input=user_input if user_input else "\n",
            text=True,
            capture_output=True,
            timeout=5
        )
        
        # Cleanup temp file
        if os.path.exists(filename):
            os.remove(filename)

        output = result.stdout if result.stdout else result.stderr
        return jsonify({"output": output, "status": "success" if not result.stderr else "error"})

    except subprocess.TimeoutExpired:
        return jsonify({"output": "Time Limit Exceeded (5s)", "status": "error"})
    except Exception as e:
        return jsonify({"output": str(e), "status": "error"})

@app.route('/submit_solution/<int:qid>', methods=['POST'])
@login_required
def submit_solution(qid):
    try:
        data = request.get_json()
        code = data.get('code', '')
        question = Question.query.get_or_404(qid)
        
        test_cases = []
        if question.test_cases:
            test_cases = json.loads(question.test_cases)

        passed = 0
        total = len(test_cases)

        # Create temp file for submission check
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
            f.write(code.encode())
            filename = f.name

        for case in test_cases:
            try:
                user_input = str(case.get('input', ''))
                res = subprocess.run(
                    ["python", filename],
                    input=user_input if user_input else "\n",
                    text=True,
                    capture_output=True,
                    timeout=5
                )
                if res.stdout.strip() == str(case.get('output', '')).strip():
                    passed += 1
            except:
                continue

        # Cleanup
        if os.path.exists(filename):
            os.remove(filename)

        score = int((passed / total) * 100) if total > 0 else 0
        status = "Passed" if passed == total and total > 0 else "Failed"
        
        # Save to DB
        new_sub = Submission(
            user_id=current_user.id,
            question_id=qid,
            code=code,
            result=f"{passed}/{total} Passed",
            score=score
        )
        db.session.add(new_sub)
        db.session.commit()

        return jsonify({
            "status": status,
            "score": score,
            "passed": passed,
            "total": total,
            "message": f"Result: {passed}/{total} test cases passed."
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/leaderboard')
@login_required
def leaderboard():
    from sqlalchemy import func
    rankings = db.session.query(User.username, func.sum(Submission.score).label('total_score')).join(Submission, User.id == Submission.user_id).filter(User.role == 'student').group_by(User.id).order_by(db.desc('total_score')).all()
    return render_template('leaderboard.html', rankings=rankings)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
