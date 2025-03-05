from flask import Flask, render_template, url_for, flash, redirect, request, send_from_directory
from forms import RegistrationForm, LoginForm, MessageForm
from models import db, User, Consultation, Message
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, current_user, logout_user, login_required
from flask_migrate import Migrate
from datetime import datetime
from werkzeug.security import generate_password_hash
import os
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres.cbvhbhvvllauonjyztan:comportaethics@aws-0-eu-west-3.pooler.supabase.com:6543/postgres'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNidmhiaHZ2bGxhdW9uanl6dGFuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzMxMjkxNjYsImV4cCI6MjA0ODcwNTE2Nn0.T-uayMxkyYChhVVx3Tz0hbbIh_xoEuo93zQOAqq_WDY'
app.config['SESSION_PERMANENT'] = False

db.init_app(app)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.init_app(app)

socketio = SocketIO(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

@app.route("/")
def home():
    return render_template('index2.html', username=current_user.username if current_user.is_authenticated else None)

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data, email=form.email.data, password=hashed_password, is_admin=False)
        try:
            db.session.add(user)
            db.session.commit()
            flash('Your account has been created! You are now able to log in', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    return render_template('register2.html', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login2.html', form=form)

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route("/messages", methods=['GET', 'POST'])
@login_required
def messages():
    form = MessageForm()

    if current_user.is_admin:
        users = User.query.filter(User.id != current_user.id).all()
        if form.validate_on_submit():
            receiver_id = request.form.get('receiver_id')
            message_content = form.content.data

            if receiver_id and message_content:
                message = Message(
                    sender_id=current_user.id,
                    receiver_id=receiver_id,
                    content=message_content,
                    timestamp=datetime.utcnow()
                )
                db.session.add(message)
                db.session.commit()

                socketio.emit('new_message', {
                    'sender': current_user.username,
                    'content': message_content,
                    'timestamp': message.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'receiver_id': receiver_id
                }, room=f'user_{receiver_id}')

                flash('Your message has been sent!', 'success')
                return redirect(url_for('messages'))

        return render_template('admin_messages.html', form=form, users=users)
    else:
        if form.validate_on_submit():
            message_content = form.content.data

            if message_content:
                message = Message(
                    sender_id=current_user.id,
                    receiver_id=1,  # Assuming user ID 1 is the admin
                    content=message_content,
                    timestamp=datetime.utcnow()
                )
                db.session.add(message)
                db.session.commit()

                socketio.emit('new_message', {
                    'sender': current_user.username,
                    'content': message_content,
                    'timestamp': message.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'receiver_id': 1
                }, room='admin')

                flash('Your message has been sent!', 'success')
                return redirect(url_for('messages'))

        received_messages = Message.query.filter_by(receiver_id=current_user.id).all()
        sent_messages = Message.query.filter_by(sender_id=current_user.id).all()

        return render_template('messages.html', form=form, received_messages=received_messages, sent_messages=sent_messages)

@socketio.on('send_message')
def handle_send_message(data):
    content = data['content']
    sender = current_user.username
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    if current_user.is_admin:
        receiver_id = data['receiver_id']
        room = f'user_{receiver_id}'
    else:
        admin_user = User.query.filter_by(is_admin=True).first()
        if admin_user:
            receiver_id = admin_user.id
        else:
            flash('No admin user found.', 'danger')
            return

        room = 'admin'

    message = Message(sender_id=current_user.id, receiver_id=receiver_id, content=content, timestamp=timestamp)
    db.session.add(message)
    db.session.commit()

    emit('new_message', {
        'sender': sender,
        'content': content,
        'timestamp': timestamp,
        'receiver_id': receiver_id
    }, room=room)

@app.route("/admin/messages")
@login_required
def admin_messages():
    if not current_user.is_admin:
        flash('Unauthorized access', 'danger')
        return redirect(url_for('home'))

    received_messages = Message.query.filter_by(receiver_id=1).all()

    users = User.query.all()
    return render_template('admin_messages.html', received_messages=received_messages, users=users)

@app.route("/submit_search", methods=['POST'])
@login_required
def submit_search():
    if request.method == 'POST':
        search_type = request.form.get('search_type')
        location = request.form.get('location')
        budget = request.form.get('budget')
        details = request.form.get('details')
        more = request.form.get('more')
        m2 = request.form.get('m2')
        subject = f"Search for {search_type} in {location}"
        if current_user.is_authenticated:
            user_id = current_user.id
            new_consultation = Consultation(
                user_id=user_id,
                subject=subject,
                description=details,
                budget=budget,
                more=more,
                m2=m2,
                status='pending',
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            try:
                db.session.add(new_consultation)
                db.session.commit()
                flash('Your search has been submitted successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
        else:
            flash('You must be logged in to submit a search.', 'danger')
            return redirect(url_for('login'))
        return redirect(url_for('home'))

@app.route("/news")
def news():
    return render_template('news.html')

@app.route("/your_search")
def your_search():
    return render_template('votre_recherche2.html')

@app.route("/our_mission")
def our_mission():
    return render_template('notre_mission2.html')

@app.route("/why_ethics")
def why_ethics():
    return render_template('pourquoi_ethics2.html')

@app.route("/purchase_process")
def purchase_process():
    return render_template('processus_achat2.html')

@app.route("/our_partnerships")
def our_partnerships():
    return render_template('nos_partenaires2.html')

@app.route('/account', methods=['GET'])
@login_required
def account():
    return render_template('account.html')

@app.route('/update_account', methods=['POST'])
@login_required
def update_account():
    username = request.form.get('username') or current_user.username
    email = request.form.get('email') or current_user.email
    phone_number = request.form.get('phone_number') or current_user.phone_number

    if not email:
        flash('Email cannot be empty.', 'danger')
        return redirect(url_for('account'))

    try:
        user = User.query.get(current_user.id)  # Fetch user by ID
        if user:
            user.username = username
            user.email = email
            user.phone_number = phone_number

            db.session.commit()
            print("Database commit successful")  # Debugging confirmation
            flash('Your account information has been updated.', 'success')
        else:
            flash('User not found.', 'danger')
    except Exception as e:
        db.session.rollback()
        print(f"Error: {str(e)}")  # Debugging output
        flash(f'An error occurred: {str(e)}', 'danger')

    return redirect(url_for('account'))

@app.route('/reset_password', methods=['POST'])
@login_required
def reset_password():
    print("Reset Password Route Triggered")  # Debugging confirmation
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not password or not confirm_password:
        flash('Both password fields are required.', 'danger')
        return redirect(url_for('account'))

    if password != confirm_password:
        flash('Passwords do not match.', 'danger')
        return redirect(url_for('account'))

    try:
        user = User.query.get(current_user.id)
        if user:
            hashed_password = generate_password_hash(password)  # Hash the new password
            user.password = hashed_password
            db.session.commit()

            flash('Your password has been reset successfully.', 'success')
        else:
            flash('User not found.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {str(e)}', 'danger')

    return redirect(url_for('account'))

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

if __name__ == "__main__":
    socketio.run(app, debug=True)
