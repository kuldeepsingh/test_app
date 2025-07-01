
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
import os
import fitz  # PyMuPDF
import re

app = Flask(__name__)
app.secret_key = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quiz.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# MODELS
class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)

class Student(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    subject = db.relationship('Subject', backref=db.backref('chapters', lazy=True))

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    chapter = db.relationship('Chapter', backref=db.backref('quizzes', lazy=True))
    title = db.Column(db.String(100))

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'))
    quiz = db.relationship('Quiz', backref=db.backref('questions', lazy=True))
    question_text = db.Column(db.Text)

class QuizResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'))
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'))
    score = db.Column(db.Integer)
    status = db.Column(db.String(20), default='assigned')

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id)) or Student.query.get(int(user_id))

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role')
        username = request.form.get('username')
        password = request.form.get('password')

        if role == 'Admin':
            user = Admin.query.filter_by(username=username, password=password).first()
        else:
            user = Student.query.filter_by(username=username, password=password).first()

        if user:
            login_user(user)
            return redirect(url_for('admin_dashboard') if user.is_admin else url_for('student_dashboard'))
        else:
            return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return "Unauthorized"
    stats = {
        'students': Student.query.count(),
        'quizzes': Quiz.query.count(),
        'questions': Question.query.count()
    }
    subjects = Subject.query.all()
    students = Student.query.all()
    quizzes = Quiz.query.all()
    results = QuizResult.query.all()
    enriched_results = []
    for result in results:
        student = Student.query.get(result.student_id)
        quiz = Quiz.query.get(result.quiz_id)
        chapter = Chapter.query.get(quiz.chapter_id)
        subject = Subject.query.get(chapter.subject_id)
        enriched_results.append({
            'student': student.username,
            'quiz': quiz.title,
            'score': result.score,
            'status': result.status,
            'subject': subject.name,
            'chapter': chapter.name
        })
    return render_template('admin_dashboard.html', stats=stats, subjects=subjects, students=students, quizzes=quizzes, results=enriched_results)

@app.route('/student')
@login_required
def student_dashboard():
    if current_user.is_admin:
        return "Unauthorized"
    results = QuizResult.query.filter_by(student_id=current_user.id).all()
    enriched_results = []
    for result in results:
        quiz = Quiz.query.get(result.quiz_id)
        chapter = Chapter.query.get(quiz.chapter_id)
        subject = Subject.query.get(chapter.subject_id)
        enriched_results.append({
            'quiz': quiz.title,
            'score': result.score,
            'subject': subject.name,
            'chapter': chapter.name
        })
    return render_template('student_dashboard.html', results=enriched_results)

@app.route('/upload_pdf', methods=['POST'])
@login_required
def upload_pdf():
    if not current_user.is_admin:
        return "Unauthorized"

    subject_name = request.form.get('subject')
    chapter_name = request.form.get('chapter')
    pdf_file = request.files.get('pdf_file')

    if not subject_name or not chapter_name or not pdf_file:
        return "Subject, Chapter, and PDF file are required."

    subject = Subject.query.filter_by(name=subject_name).first()
    if not subject:
        subject = Subject(name=subject_name)
        db.session.add(subject)
        db.session.commit()

    chapter = Chapter.query.filter_by(name=chapter_name, subject_id=subject.id).first()
    if not chapter:
        chapter = Chapter(name=chapter_name, subject_id=subject.id)
        db.session.add(chapter)
        db.session.commit()

    quiz = Quiz(title=f"Quiz on {chapter_name}", chapter_id=chapter.id)
    db.session.add(quiz)
    db.session.commit()

    os.makedirs("temp", exist_ok=True)
    temp_path = os.path.join("temp", pdf_file.filename)
    pdf_file.save(temp_path)

    with fitz.open(temp_path) as doc:
        text = "".join(page.get_text() for page in doc)
    os.remove(temp_path)

    question_blocks = re.findall(
        r"Q\d+\.\s*(.*?)\n\s*A\.\s*(.*?)\n\s*B\.\s*(.*?)\n\s*C\.\s*(.*?)\n\s*D\.\s*(.*?)(?=\nQ\d+\.|$)",
        text, re.DOTALL)

    preview_questions = []
    for block in question_blocks[:100]:
        q_text, a, b, c, d = [x.strip() for x in block]
        full_text = f"{q_text}\nA. {a}\nB. {b}\nC. {c}\nD. {d}"
        preview_questions.append(full_text)

    session['quiz_id'] = quiz.id
    session['quiz_questions'] = preview_questions
    return render_template('quiz_preview.html', questions=preview_questions, quiz_id=quiz.id)

@app.route('/confirm_quiz_upload', methods=['POST'])
@login_required
def confirm_quiz_upload():
    if not current_user.is_admin:
        return "Unauthorized"
    quiz_id = session.get('quiz_id')
    questions = session.get('quiz_questions')
    if not quiz_id or not questions:
        return redirect(url_for('admin_dashboard'))
    for q in questions:
        question = Question(quiz_id=quiz_id, question_text=q)
        db.session.add(question)
    db.session.commit()
    session.pop('quiz_id', None)
    session.pop('quiz_questions', None)
    return redirect(url_for('admin_dashboard'))

@app.route('/generate_test/<int:chapter_id>', methods=['POST'])
@login_required
def generate_test(chapter_id):
    if not current_user.is_admin:
        return "Unauthorized"
    chapter = Chapter.query.get_or_404(chapter_id)
    quiz = Quiz(title=f"Auto Quiz on {chapter.name}", chapter_id=chapter.id)
    db.session.add(quiz)
    db.session.commit()
    questions = Question.query.join(Quiz).filter(Quiz.chapter_id == chapter_id).limit(100).all()
    for q in questions:
        copied_question = Question(quiz_id=quiz.id, question_text=q.question_text)
        db.session.add(copied_question)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#generate-test')

@app.route('/assign_test', methods=['POST'])
@login_required
def assign_test():
    if not current_user.is_admin:
        return "Unauthorized"
    quiz_id = int(request.form.get('quiz_id'))
    student_ids = request.form.getlist('student_ids')
    for sid in student_ids:
        existing = QuizResult.query.filter_by(quiz_id=quiz_id, student_id=sid).first()
        if not existing:
            result = QuizResult(
                quiz_id=quiz_id,
                student_id=sid,
                score=0,
                status='assigned'
            )
            db.session.add(result)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#assign-test')

@app.route('/admin/add_student', methods=['POST'])
@login_required
def add_student():
    if not current_user.is_admin:
        return "Unauthorized"
    username = request.form['username']
    password = request.form['password']
    if Student.query.filter_by(username=username).first():
        return "Student already exists."
    student = Student(username=username, password=password)
    db.session.add(student)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#manage-students')

@app.route('/admin/delete_student/<int:student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    if not current_user.is_admin:
        return "Unauthorized"
    student = Student.query.get_or_404(student_id)
    db.session.delete(student)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#manage-students')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Admin.query.filter_by(username='admin').first():
            db.session.add(Admin(username='admin', password='admin'))
        if not Student.query.filter_by(username='bob').first():
            db.session.add(Student(username='bob', password='bob'))
        if not Student.query.filter_by(username='alice').first():
            db.session.add(Student(username='alice', password='alice'))
        for subj in ['Maths', 'English', 'Physics', 'Chemistry', 'Biology', 'Geography', 'Civics', 'History']:
            if not Subject.query.filter_by(name=subj).first():
                db.session.add(Subject(name=subj))
        db.session.commit()
    app.run(debug=True)
