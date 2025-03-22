from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from database import get_database_connection
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime  # Add this at the top with other imports
# import razorpay  # Comment this line

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Comment out Razorpay client initialization
# razorpay_client = razorpay.Client(auth=("YOUR_KEY_ID", "YOUR_KEY_SECRET"))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'is_admin' not in session or not session['is_admin']:
            flash('Admin access required', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_database_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['user_name'] = user['full_name']
                
                if email == 'admin@gmail.com':
                    session['is_admin'] = True
                    print("Admin login successful")  # Debug print
                    cursor.close()
                    conn.close()
                    return redirect(url_for('admin_dashboard'))
                
                flash('Login successful!', 'success')
                cursor.close()
                conn.close()
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid email or password', 'error')
            
            cursor.close()
            conn.close()
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        password = request.form['password']
        
        conn = get_database_connection()
        if conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                if cursor.fetchone():
                    flash('Email already registered!', 'error')
                    return render_template('signup.html')
                
                cursor.execute("""
                    INSERT INTO users (full_name, email, password)
                    VALUES (%s, %s, %s)
                """, (full_name, email, generate_password_hash(password)))
                conn.commit()
                flash('Registration successful! Please login.', 'success')
                return redirect(url_for('login'))
            except Exception as e:
                flash('An error occurred. Please try again.', 'error')
                print(f"Database error: {e}")
            finally:
                cursor.close()
                conn.close()
    
    return render_template('signup.html')

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_database_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('dashboard.html', user=user, datetime=datetime)

@app.route('/api/stations/nearby', methods=['POST'])
@login_required
def nearby_stations():
    data = request.json
    lat = data['latitude']
    lng = data['longitude']
    radius = data.get('radius', 10)  # Default 10km radius
    
    conn = get_database_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Using Haversine formula to calculate distance
    cursor.execute("""
        SELECT *, 
        (6371 * acos(cos(radians(%s)) * cos(radians(latitude)) * 
        cos(radians(longitude) - radians(%s)) + sin(radians(%s)) * 
        sin(radians(latitude)))) AS distance 
        FROM charging_stations 
        HAVING distance < %s 
        ORDER BY distance
    """, (lat, lng, lat, radius))
    
    stations = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return jsonify({'stations': stations})

@app.route('/api/bookings', methods=['POST'])
@login_required
def create_booking():
    data = request.json
    station_id = data['station_id']
    booking_date = data['date']
    start_time = data['start_time']
    duration = int(data['duration'])
    
    conn = get_database_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Get station details
        cursor.execute("SELECT * FROM charging_stations WHERE id = %s", (station_id,))
        station = cursor.fetchone()
        
        if not station:
            return jsonify({'error': 'Station not found'}), 404
            
        # Calculate total amount
        total_amount = station['price_per_hour'] * duration
        
        # Temporary: Skip Razorpay integration
        # Create booking directly
        cursor.execute("""
            INSERT INTO bookings (user_id, station_id, booking_date, start_time, 
                                duration, total_amount, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'confirmed')
        """, (session['user_id'], station_id, booking_date, start_time, 
              duration, total_amount))
        
        booking_id = cursor.lastrowid
        conn.commit()
        
        return jsonify({
            'booking_id': booking_id,
            'message': 'Booking created successfully'
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/bookings', methods=['GET'])
@login_required
def get_bookings():
    conn = get_database_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT b.*, s.name as station_name, s.address
        FROM bookings b 
        JOIN charging_stations s ON b.station_id = s.id 
        WHERE b.user_id = %s
        ORDER BY b.created_at DESC
    """, (session['user_id'],))
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({'bookings': bookings})

@app.route('/api/bookings/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    conn = get_database_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE bookings 
            SET status = 'cancelled' 
            WHERE id = %s AND user_id = %s AND status = 'pending'
        """, (booking_id, session['user_id']))
        conn.commit()
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Booking not found or cannot be cancelled'}), 400
            
        return jsonify({'message': 'Booking cancelled successfully'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/profile', methods=['PUT'])
@login_required
def update_profile():
    data = request.json
    conn = get_database_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE users 
            SET full_name = %s
            WHERE id = %s
        """, (data['full_name'], session['user_id']))
        conn.commit()
        
        session['user_name'] = data['full_name']
        return jsonify({'message': 'Profile updated successfully'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('home'))

# Remove these routes as they're no longer needed
# @app.route('/bookings')
# @app.route('/profile')
@login_required
def bookings():
    return render_template('bookings.html', user=user, datetime=datetime)

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=user, datetime=datetime)

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    print("Accessing admin dashboard")  # Debug print
    try:
        # Get statistics using the database connection from your configuration
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT COUNT(*) as total FROM charging_stations")
        total_stations = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM bookings WHERE status = 'confirmed'")
        active_bookings = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total_users = cursor.fetchone()['total']
        
        cursor.execute("SELECT SUM(total_amount) as total FROM bookings WHERE status != 'cancelled'")
        total_revenue = cursor.fetchone()['total'] or 0
        
        cursor.close()
        conn.close()
        
        return render_template('admin_dashboard.html',
                            total_stations=total_stations,
                            active_bookings=active_bookings,
                            total_users=total_users,
                            total_revenue=total_revenue)
    except Exception as e:
        print(f"Error in admin dashboard: {e}")
        flash('Error loading admin dashboard', 'error')
        return redirect(url_for('login'))

# Add these imports if not already present
from flask import jsonify
import mysql.connector

# Add database configuration
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'ev_charging'
}

# Add these routes to handle charging stations
@app.route('/api/stations', methods=['GET'])
@app.route('/api/stations')
@login_required
def get_stations():
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, name, address, district, latitude, longitude, 
                   connector_type, charging_speed, power_rating, 
                   status, price_per_hour 
            FROM charging_stations
        """)
        stations = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Convert Decimal objects to float for JSON serialization
        for station in stations:
            station['latitude'] = float(station['latitude'])
            station['longitude'] = float(station['longitude'])
            station['power_rating'] = float(station['power_rating'])
            station['price_per_hour'] = float(station['price_per_hour'])
        
        return jsonify({'stations': stations})
    except Exception as e:
        print(f"Error fetching stations: {e}")
        return jsonify({'error': 'Failed to fetch stations'}), 500

@app.route('/api/stations/<int:station_id>', methods=['GET'])
def get_station(station_id):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, name, address, latitude, longitude, 
                   price_per_hour, available 
            FROM charging_stations 
            WHERE id = %s
        """, (station_id,))
        
        station = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if station:
            return jsonify({'success': True, 'station': station})
        return jsonify({'success': False, 'error': 'Station not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/stations', methods=['GET'])
@admin_required
def get_admin_stations():
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, name, address, latitude, longitude, 
                   price_per_hour, available 
            FROM charging_stations
            ORDER BY id DESC
        """)
        
        stations = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'stations': stations})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/stations', methods=['POST'])
@admin_required
def add_station():
    try:
        data = request.json
        conn = get_database_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO charging_stations (name, address, latitude, longitude, price_per_hour)
            VALUES (%s, %s, %s, %s, %s)
        """, (data['name'], data['address'], data['latitude'], data['longitude'], data['price_per_hour']))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Station added successfully'})
    except Exception as e:
        print(f"Error adding station: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/stations')
@admin_required
def admin_stations():
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM charging_stations ORDER BY id DESC")
        stations = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('admin_stations.html', stations=stations)
    except Exception as e:
        print(f"Error loading stations: {e}")
        flash('Error loading stations', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/bookings')
@admin_required
def admin_bookings():
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT b.*, u.full_name as user_name, s.name as station_name 
            FROM bookings b 
            JOIN users u ON b.user_id = u.id 
            JOIN charging_stations s ON b.station_id = s.id 
            ORDER BY b.created_at DESC
        """)
        bookings = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('admin_bookings.html', bookings=bookings)
    except Exception as e:
        print(f"Error loading bookings: {e}")
        flash('Error loading bookings', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@admin_required
def admin_users():
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT u.*, COUNT(b.id) as total_bookings 
            FROM users u 
            LEFT JOIN bookings b ON u.id = b.user_id 
            GROUP BY u.id 
            ORDER BY u.created_at DESC
        """)
        users = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('admin_users.html', users=users)
    except Exception as e:
        print(f"Error loading users: {e}")
        flash('Error loading users', 'error')
        return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
    