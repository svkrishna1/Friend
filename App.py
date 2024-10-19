from flask import Flask, request, jsonify, session, url_for, send_from_directory
import os
import re
import sqlite3
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app, supports_credentials=True)  # Allow credentials like session cookies
# app.secret_key = '12345678'  # Replace with your own secret key

# # Replace this with your actual Google Client ID
# GOOGLE_CLIENT_ID = '431139954033-qojco015bem2g6q31fafcgt20bhn49bc.apps.googleusercontent.com'
# GOOGLE_CLIENT_SECRET = 'YOUR_GOOGLE_CLIENT_SECRET'  # Add your client secret

class Database:
    def __init__(self, db_name='users.db'):
        self.connection = sqlite3.connect(db_name, check_same_thread=False)  # Allow multi-threading
        self.create_table()

    def create_table(self):
        with self.connection:
            self.connection.execute(''' 
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    age TEXT
                )
            ''')

    def add_user(self, username, password):
        with self.connection:
            self.connection.execute(''' 
                INSERT INTO users (username, password) VALUES (?, ?)
            ''', (username, password))

    def get_user(self, username):
        cursor = self.connection.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        return cursor.fetchone()

    def update_password(self, username, new_password):
        with self.connection:
            self.connection.execute(''' 
                UPDATE users SET password = ? WHERE username = ?
            ''', (new_password, username))

    def save_user_age(self, username, age):
        with self.connection:
            self.connection.execute(''' 
                UPDATE users SET age = ? WHERE username = ?
            ''', (age, username))

    def get_user_profile(self, username):
        cursor = self.connection.cursor()
        cursor.execute('SELECT username, age FROM users WHERE username = ?', (username,))
        return cursor.fetchone()

    def close(self):
        self.connection.close()

@app.route('/register', methods=['POST'])
def register():
    if request.method == 'POST':
        data = request.get_json()
        username = data['username']
        password = data['password']
        confirm_password = data['confirm_password']

        db = Database()
        
        if not username:
            return jsonify({'error': 'Username cannot be empty.'}), 400
        elif password != confirm_password:
            return jsonify({'error': 'Passwords do not match.'}), 400
        
        user = db.get_user(username)
        if user:
            return jsonify({'error': 'Username is already taken.'}), 400
        
        password_errors = validate_password(password)
        if password_errors:
            return jsonify({'errors': password_errors}), 400
        
        db.add_user(username, password)
        db.close()
        return jsonify({'message': f"User '{username}' registered successfully!"}), 200

@app.route('/login', methods=['POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        username = data['username']
        password = data['password']
        db = Database()
        user = db.get_user(username)
        if user and user[2] == password:
            session['username'] = username  # Store username in session
            return jsonify({'message': f"Login successful! Welcome, {username}."}), 200
        else:
            return jsonify({'message': "Invalid username or password."}), 400


def validate_password(password):
    errors = []
    if len(password) < 6:
        errors.append("Password must be at least 6 characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        errors.append("Password must contain at least one special character.")
    return errors

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)  # Remove username from session
    return jsonify({'message': 'Logged out successfully'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
