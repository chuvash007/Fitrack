from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt
import os
import sqlite3
from datetime import datetime
import pandas as pd
from io import StringIO


app = Flask(__name__)
if not os.path.exists('static'):
    os.makedirs('static')

app.secret_key = 'bigsecret'
login_manager = LoginManager(app)
login_manager.login_view = 'login'

uploaded_data = pd.DataFrame()

DATABASE = 'fitness_data.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fitness_data
                 (user_id INTEGER,
                  date TEXT,
                  calories_burned INTEGER,
                  calories_consumed INTEGER,
                  workout_done INTEGER,
                  FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    conn.close()

class User(UserMixin):
    def __init__(self, id, username, email):
        self.id = id
        self.username = username
        self.email = email

def get_db():
    conn = sqlite3.connect(DATABASE)
    return conn

def save_to_db(df):
    conn = get_db()
    df.to_sql('fitness_data', conn, if_exists='replace', index=False)
    conn.close()

def load_from_db():
    conn = get_db()
    df = pd.read_sql('SELECT * FROM fitness_data ORDER BY date', conn)
    conn.close()
    return df


init_db()
uploaded_data = load_from_db()


@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(id=user[0], username=user[1], email=user[2])
    return None


@app.route("/")
def home():
  return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[3], password):
            user_obj = User(id=user[0], username=user[1], email=user[2])
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        
        flash('Invalid email or password')
        return redirect(url_for('login'))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match')
            return redirect(url_for('register'))

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        try:
            hashed_pw = generate_password_hash(password)
            c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                     (username, email, hashed_pw))
            conn.commit()
            flash('Registration successful! Please login')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists')
            return redirect(url_for('register'))
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


def filter_data(df, time_range):
    if df.empty:
        return df
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    latest = df['date'].max()
    
    if time_range == '7days':
        return df[df['date'] >= (latest - pd.DateOffset(days=6))]
    elif time_range == 'month':
        return df[df['date'].dt.month == latest.month]
    elif time_range == 'year':
        return df[df['date'].dt.year == latest.year]
    return df


@app.route("/dashboard")
@login_required
def dashboard():
    global uploaded_data
    time_range = request.args.get('range', 'all')
    
    # Filter data based on selection
    filtered_data = filter_data(uploaded_data, time_range) if not uploaded_data.empty else pd.DataFrame()
    generate_charts(filtered_data)
    
    recent_entries = filtered_data.tail(10).to_dict('records') if not filtered_data.empty else []
    return render_template("dashboard.html", 
                         recent_entries=recent_entries,
                         has_data=not uploaded_data.empty,
                         current_range=time_range,
                         user=current_user)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    global uploaded_data
    if request.method == 'POST':
        if "csv_file" not in request.files:
            return "No file selected", 400
        
        file = request.files["csv_file"]
        if file.filename == "":
            return "No file selected", 400

        if file and file.filename.endswith(".csv"):
            try:
                df = pd.read_csv(StringIO(file.stream.read().decode("utf-8")))
                required_cols = ['date', 'calories_burned', 'calories_consumed', 'workout_done']
                if not all(col in df.columns for col in required_cols):
                    return "CSV missing required columns", 400
                
                uploaded_data = df
                save_to_db(df)
                generate_charts(df)
                return "File uploaded successfully! Charts updated.", 200
            except Exception as e:
                return f"Error processing CSV: {str(e)}", 400
        else:
            return "Only CSV files are supported!", 400
    return "Upload page"

# Fix styling
def generate_charts(df):
    try:
        if df.empty:
            open('static/calories_chart.png', 'w').close()
            open('static/workout_chart.png', 'w').close()
            return

        plt.style.use('seaborn-v0_8')
        
        df['date'] = pd.to_datetime(df['date'])
        
    
        plt.figure(figsize=(12,5))
        plt.plot(df['date'], df['calories_burned'], 
                '#4361ee', linewidth=2.5, marker='o', markersize=5)
        plt.title('Calories Burned', fontsize=14, pad=15)
        plt.xticks(rotation=45)
        plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig('static/calories_chart.png', dpi=100, bbox_inches='tight')
        plt.close()
        
        plt.figure(figsize=(12,5))
        df['week'] = df['date'].dt.strftime('%b %d')
        df.groupby('week')['workout_done'].sum().plot(
            kind='bar', color='#21A179', width=0.7, edgecolor='white')
        plt.title('Workouts Completed', fontsize=14, pad=15)
        plt.xticks(rotation=45)
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig('static/workout_chart.png', dpi=100, bbox_inches='tight')
        plt.close()
        
        return True
    except Exception as e:
        print(f"Error generating charts: {e}")
        return False


if __name__ == "__main__":
  app.run(debug=True)