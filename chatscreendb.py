from flask import Flask, request, jsonify, url_for, send_from_directory, session
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import speech_recognition as sr
import io
import sqlite3
from google.cloud import vision
import pyttsx3
import requests
import os
from flask_cors import CORS
import json
import re

app = Flask(__name__)
CORS(app, supports_credentials=True)  # Allow credentials like session cookies
app.secret_key = '12345678120'  # Replace with your own secret key

# Replace this with your actual Google Client ID
GOOGLE_CLIENT_ID = '431139954033-qojco015bem2g6q31fafcgt20bhn49bc.apps.googleusercontent.com'
GOOGLE_CLIENT_SECRET = 'YOUR_GOOGLE_CLIENT_SECRET'  # Add your client secret

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

# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=8080, debug=True)

# Configuration for image uploads
UPLOAD_FOLDER = 'uploads'  # Folder where the images will be uploaded
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Ensure the upload folder exists

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

# Store chat history and handle user input
@app.route("/input", methods=["POST"])
def handle_user_input():
    if request.content_type == 'application/json':
        try:
            # Parse the JSON data
            data = request.get_json()
            input_method = data.get('input_method')
            user_input = data.get('user_input')
            username = data.get('username', 'Anonymous')

            # Process the user input and generate a response
            if input_method == 'text':
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

# Initialize Flask application
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = './uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# Set up your Google credentials and Gemini API details
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "C:/Users/venka/Downloads/gen-lang-client-0761504501-08d88fc2cc9e.json"
GEMINI_API_KEY = "AIzaSyBymNK3rpOCL15LVqVP5WJQWrIv3cVf5Gk"
GEMINI_API_URL = 'https://generativelanguage.googleapis.com/v1beta2/models/gemini-1.5-pro:generateText'

# Ensure the upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def generate_text_with_gemini(image_info):
    """Generate text using the Gemini API based on the image information."""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {GEMINI_API_KEY}',
    }

    prompt = {
        'prompt': {
            'text': f"Generate a detailed description based on the following image labels: {image_info}"
        },
    }

    response = requests.post(GEMINI_API_URL, headers=headers, json=prompt)

    if response.status_code == 200:
        response_data = response.json()
        generated_text = response_data.get('candidates', [])[0].get('output', 'No output generated')
        return generated_text
    else:
        print(f"Error with Gemini API: {response.status_code} {response.text}")
        return None

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and generate information about the uploaded image."""
    if 'file' not in request.files:
        return jsonify({'message': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'message': 'No selected file'}), 400

    if not allowed_file(file.filename):
        return jsonify({'message': 'File type not allowed'}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    # Extract information from the image (using Google Vision API is optional here)
    image_info = "label1, label2, label3"  # Replace with actual image analysis if needed

    # Generate description using Gemini
    generated_description = generate_text_with_gemini(image_info)

    return jsonify({'message': generated_description, 'image_url': f"/uploads/{filename}"}), 200

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve the uploaded file."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Flask app running
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
