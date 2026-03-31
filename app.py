import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'codehub.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Database Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
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
    # Create a default admin if it doesn't exist
    if not User.query.filter_by(username='admin').first():
        admin_user = User(
            username='admin',
            password=generate_password_hash('admin123'),
            role='admin'
        )
        db.session.add(admin_user)
        db.session.commit()

# --- Routes ---

@app.route('/')
@login_required
def admin_panel():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    questions = Question.query.all()
    students = User.query.filter_by(role='student').all()
    submissions = Submission.query.all()
    return render_template('admin.html', questions=questions, students=students, submissions=submissions)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Debug prints to verify input (check terminal/console)
        print(f"[DEBUG] Login attempt - Username: {username}")
        
        user = User.query.filter_by(username=username).first()
        
        if user:
            print(f"[DEBUG] User found in database: {user.username}, Role: {user.role}")
            # Verify password hash
            is_valid = check_password_hash(user.password, password)
            print(f"[DEBUG] Password valid: {is_valid}")
            
            if is_valid:
                login_user(user)
                flash(f'Welcome, {username}!', 'success')
                if user.role == 'admin':
                    return redirect(url_for('admin_panel'))
                return redirect(url_for('dashboard'))
            else:
                print(f"[DEBUG] Password mismatch for user: {username}")
        else:
            print(f"[DEBUG] No user found with username: {username}")
            
        flash('Invalid username or password.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/admin/add_question', methods=['POST'])
@login_required
def add_question():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    title = request.form.get('title')
    description = request.form.get('description')
    answer = request.form.get('answer')
    
    new_question = Question(title=title, description=description, answer=answer)
    db.session.add(new_question)
    db.session.commit()
    flash('Question added successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/generate_student', methods=['POST'])
@login_required
def generate_student():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'danger')
    else:
        # Use default hashing method for better compatibility
        new_student = User(
            username=username,
            password=generate_password_hash(password),
            role='student'
        )
        db.session.add(new_student)
        db.session.commit()
        flash(f'Student {username} created successfully!', 'success')
        
    return redirect(url_for('admin_panel'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'student':
        return redirect(url_for('admin_panel'))
    
    questions = Question.query.all()
    # To check if student already submitted a question
    user_submissions = {s.question_id: s for s in current_user.submissions}
    return render_template('dashboard.html', questions=questions, user_submissions=user_submissions)

@app.route('/submit/<int:question_id>', methods=['POST'])
@login_required
def submit_answer(question_id):
    if current_user.role != 'student':
        flash('Only students can submit answers.', 'danger')
        return redirect(url_for('admin_panel'))
    
    student_answer = request.form.get('answer')
    
    # Check if student already submitted for this question
    existing = Submission.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    if existing:
        existing.answer = student_answer
        flash('Submission updated!', 'success')
    else:
        new_submission = Submission(user_id=current_user.id, question_id=question_id, answer=student_answer)
        db.session.add(new_submission)
        flash('Answer submitted successfully!', 'success')
        
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/leaderboard')
@login_required
def leaderboard():
    # Rank students by submission count
    from sqlalchemy import func
    rankings = db.session.query(
        User.username, 
        func.count(Submission.id).label('score')
    ).join(Submission, User.id == Submission.user_id, isouter=True)\
     .filter(User.role == 'student')\
     .group_by(User.id)\
     .order_by(db.desc('score'))\
     .all()
     
    return render_template('leaderboard.html', rankings=rankings)

if __name__ == '__main__':
    app.run(debug=True)
