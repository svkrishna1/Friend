from flask import Flask, request, jsonify, session, send_from_directory
import os
import re
import sqlite3
from flask_cors import CORS
from werkzeug.utils import secure_filename
import speech_recognition as sr
import requests
from google.cloud import vision
import pyttsx3
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app, supports_credentials=True)  # Allow credentials like session cookies
app.secret_key = '12345678'  # Replace with your own secret key

# Configuration for image uploads
# Set your upload folder and allowed file types
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# SQLite Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat_history.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize the recognizer and text-to-speech engine
recognizer = sr.Recognizer()
tts_engine = pyttsx3.init()

# Your Gemini API key
GEMINI_API_KEY = "AIzaSyBymNK3rpOCL15LVqVP5WJQWrIv3cVf5Gk"  # Replace with your actual API key
GEMINI_MODEL = "gemini-1.5-pro"  # Change this if needed
GEMINI_API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent'

# Chat history database model
class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_message = db.Column(db.String(500), nullable=False)
    ai_response = db.Column(db.String(500), nullable=False)
    username = db.Column(db.String(100), nullable=False)

# Create database
with app.app_context():
    db.create_all()

# Database for user authentication
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

    def close(self):
        self.connection.close()

# Function to convert speech from the microphone to text
def speech_to_text_from_mic():
    with sr.Microphone() as source:
        print("Please speak something...")
        audio = recognizer.listen(source)
        try:
            recognized_text = recognizer.recognize_google(audio)
            return recognized_text
        except sr.UnknownValueError:
            return "Sorry, I could not understand the audio."
        except sr.RequestError as e:
            return f"Could not request results from Google Speech Recognition service; {e}"

# Function to communicate with the AI model
def generate_model_response(user_input):
    headers = {
        'Content-Type': 'application/json',
    }
    data = {
        "contents": [
            {
                "parts": [
                    {"text": user_input}
                ]
            }
        ]
    }
    response = requests.post(GEMINI_API_URL, headers=headers, json=data, params={"key": GEMINI_API_KEY})

    if response.status_code == 200:
        response_data = response.json()
        if "candidates" in response_data and len(response_data["candidates"]) > 0:
            model_response = response_data["candidates"][0]
            if "content" in model_response:
                return model_response["content"]["parts"][0]["text"].strip()
            else:
                return "Error: Unexpected response structure from the Gemini API."
        else:
            return "Error: No response content from the Gemini API."
    else:
        return f"API Error: {response.status_code}, {response.content}"

import base64

def send_image_to_gemini_api(image_path):
    # Read the image file as binary
    with open(image_path, "rb") as image_file:
        # Convert the image to a base64 string
        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

    # Gemini API might require a specific JSON structure for images
    headers = {
        'Content-Type': 'application/json',
    }

    # Adjust payload to the API's expected structure for image data
    data = {
        "model": GEMINI_MODEL,
        "image": {
            "content": encoded_image  # Base64 encoded image
        }
    }

    params = {"key": GEMINI_API_KEY}
    
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, json=data, params=params)
        
        if response.status_code == 200:
            return response.json()  # Return the API's response
        else:
            return f"API Error: {response.status_code}, {response.content.decode('utf-8')}"
    except Exception as e:
        return f"Exception occurred: {str(e)}"

# Store chat history and handle user input
@app.route("/input", methods=["POST"])
def handle_user_input():
    if request.content_type == 'application/json':
        try:
            # Parse the JSON data
            data = request.get_json()
            input_method = data.get('method')  # Changed from 'input_method'
            user_input = data.get('text')  # Changed from 'user_input'
            username = data.get('username', 'Anonymous')

            if input_method == 'text':
                # Generate AI response from the user input (text)
                ai_response = generate_model_response(user_input)

                # Store the conversation in the database
                new_chat = ChatHistory(user_message=user_input, ai_response=ai_response, username=username)
                db.session.add(new_chat)
                db.session.commit()

                return jsonify({
                    "message": ai_response, 
                    "chat_history": get_chat_history(username)  # Send chat history back
                }), 200
            elif input_method == 'mic':
                # Use speech-to-text recognition for mic input
                recognized_text = speech_to_text_from_mic()
                ai_response = generate_model_response(recognized_text)

                # Store the conversation in the database
                new_chat = ChatHistory(user_message=recognized_text, ai_response=ai_response, username=username)
                db.session.add(new_chat)
                db.session.commit()

                return jsonify({
                    "message": ai_response, 
                    "chat_history": get_chat_history(username)  # Send chat history back
                }), 200
            else:
                return jsonify({"error": "Invalid input method. Please specify 'text' or 'mic'."}), 400
        except Exception as e:
            return jsonify({"error": "Invalid JSON data", "details": str(e)}), 400
    else:
        return jsonify({"error": "Unsupported media type. Expected 'application/json'"}), 415

# Retrieve chat history
def get_chat_history(username):
    chats = ChatHistory.query.filter_by(username=username).all()
    return [{"user": chat.user_message, "ai": chat.ai_response} for chat in chats]

# User registration route
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

# User login route
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

# Password validation function
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

# Age update route
@app.route('/age', methods=['POST'])
def update_age():
    if request.method == 'POST':
        data = request.get_json()
        age = data.get('age')

        # Update the age in the database
        with db.connection:
            db.connection.execute('UPDATE users SET age = ? WHERE username = ?', (age))

        return jsonify({'message': 'Age updated successfully.'}), 200

# User logout route
@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)  # Remove username from session
    return jsonify({'message': 'Logged out successfully'}), 200

# File upload route
@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and generate information about the uploaded image."""
    # Check if the post request has the file part
    if 'file' not in request.files:
        return jsonify({'message': 'No file part'}), 400

    file = request.files['file']

    # If the user does not select a file, the browser submits an empty file without a filename
    if file.filename == '':
        return jsonify({'message': 'No selected file'}), 400

    # Check if the file is allowed
    if not allowed_file(file.filename):
        return jsonify({'message': 'File type not allowed'}), 400

    # Secure the filename and save the file
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    # Save the file
    file.save(file_path)

    return jsonify({'message': 'File uploaded successfully', 'filename': filename}), 201

# Serve uploaded files
@app.route('/uploads/<path:filename>', methods=['GET'])
def uploaded_file(filename):
    """Serve the uploaded files."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
