from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
from database import get_database_connection
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime  
import razorpay  
import os
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

razorpay_client = razorpay.Client(auth=("rzp_test_pMobRZO0cAbjdt", "YOUR_SECRET_KEY"))

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
        
        if email == "admin@gmail.com" and password == "admin":
            conn = get_database_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Get or create admin user
            cursor.execute("SELECT * FROM users WHERE email = 'admin@gmail.com'")
            admin = cursor.fetchone()
            
            if not admin:
                # Create admin user if doesn't exist
                cursor.execute("""
                    INSERT INTO users (full_name, email, password)
                    VALUES ('Administrator', 'admin@gmail.com', %s)
                """, (generate_password_hash('admin'),))
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE email = 'admin@gmail.com'")
                admin = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            session['user_id'] = admin['id']
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        
        conn = get_database_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()
                
                if user:
                    print("Found user:", user)
                    print("Entered password:", password)
                    
                    if check_password_hash(user['password'], password):
                        session['user_id'] = user['id']
                        session['user_name'] = user['full_name']
                        return redirect(url_for('dashboard'))
                    
                flash('Invalid email or password', 'danger')
            except Exception as e:
                print("Database error:", e)
                flash('An error occurred. Please try again.', 'danger')
            finally:
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
    radius = data.get('radius', 10)  
    
    conn = get_database_connection()
    cursor = conn.cursor(dictionary=True)
    
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
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('index'))  # Make sure this uses 'index'

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
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get total stations
        cursor.execute("SELECT COUNT(*) as total FROM charging_stations")
        total_stations = cursor.fetchone()['total']
        
        # Get active bookings (pending or confirmed)
        cursor.execute("""
            SELECT COUNT(*) as total FROM bookings 
            WHERE status IN ('pending', 'confirmed')
        """)
        active_bookings = cursor.fetchone()['total']
        
        # Get total users
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total_users = cursor.fetchone()['total']
        
        # Get total revenue
        cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0) as total 
            FROM bookings 
            WHERE status NOT IN ('cancelled')
        """)
        total_revenue = cursor.fetchone()['total']
        
        # Get stations with detailed info
        cursor.execute("""
            SELECT *, 
                (SELECT COUNT(*) FROM bookings b 
                 WHERE b.station_id = cs.id 
                 AND b.status NOT IN ('cancelled')) as total_bookings
            FROM charging_stations cs
            ORDER BY created_at DESC
        """)
        stations = cursor.fetchall()
        
        # Get recent bookings with user and station details
        cursor.execute("""
            SELECT b.*, u.full_name, s.name as station_name,
                   s.connector_type, s.charging_speed
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            JOIN charging_stations s ON b.station_id = s.id
            ORDER BY b.created_at DESC
            LIMIT 10
        """)
        recent_bookings = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('admin_dashboard.html',
                             total_stations=total_stations,
                             active_bookings=active_bookings,
                             total_users=total_users,
                             total_revenue=total_revenue,
                             stations=stations,
                             recent_bookings=recent_bookings)
                             
    except Exception as e:
        print(f"Error loading dashboard: {e}")
        flash('Error loading dashboard data', 'error')
        return redirect(url_for('admin_login'))

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
            INSERT INTO charging_stations (
                name, address, district, latitude, longitude,
                connector_type, charging_speed, power_rating,
                status, price_per_hour
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data['name'],
            data['address'],
            data['district'],
            data['latitude'],
            data['longitude'],
            data['connector_type'],
            data['charging_speed'],
            data['power_rating'],
            data['status'],
            data['price_per_hour']
        ))
        
        conn.commit()
        station_id = cursor.lastrowid
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Station added successfully',
            'station_id': station_id
        })
        
    except Exception as e:
        print(f"Error adding station: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin/stations')
@admin_required
def admin_stations():
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, name, address, district, latitude, longitude,
                   connector_type, charging_speed, power_rating,
                   status, price_per_hour, created_at
            FROM charging_stations 
            ORDER BY created_at DESC
        """)
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

@app.route('/user_station_booking')
def user_station_booking():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('user_station_booking.html')

@app.route('/save_booking', methods=['POST'])
def save_booking():
    try:
        data = request.get_json()
        conn = get_database_connection()
        cursor = conn.cursor()

        # First check if this exact payment has already been processed
        cursor.execute("SELECT id FROM bookings WHERE razorpayid = %s", (data['razorpayid'],))
        existing_payment = cursor.fetchone()
        
        if existing_payment:
            return jsonify({
                'success': True,
                'message': 'Booking already confirmed'
            })

        # Parse booking times
        booking_date = data['booking_date']
        booking_start_time = data['start_time']
        duration_hours = int(data['duration'])

        # Check for overlapping bookings
        cursor.execute("""
            SELECT * FROM bookings 
            WHERE station_id = %s 
            AND booking_date = %s 
            AND status NOT IN ('cancelled', 'Finished')
            AND (
                (start_time < ADDTIME(%s, SEC_TO_TIME(%s * 3600)) 
                AND ADDTIME(start_time, SEC_TO_TIME(duration * 3600)) > %s)
            )
        """, (
            data['station_id'],
            booking_date,
            booking_start_time,
            duration_hours,
            booking_start_time
        ))
        
        conflicting_bookings = cursor.fetchall()
        
        if conflicting_bookings:
            return jsonify({
                'success': False, 
                'message': 'This time slot overlaps with an existing booking. Please choose a different time.'
            }), 409

        # If no conflicts, proceed with saving the new booking
        cursor.execute("""
            INSERT INTO bookings (
                user_id, station_id, booking_date, start_time, 
                duration, total_amount, status, razorpayid
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            session['user_id'],
            data['station_id'],
            booking_date,
            booking_start_time,
            duration_hours,
            data['total_amount'],
            data['status'],
            data['razorpayid']
        ))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Booking saved successfully'})
        
    except Exception as e:
        print("Error saving booking:", str(e))
        return jsonify({'success': False, 'message': 'Error saving booking: ' + str(e)}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@app.route('/user/cancel-booking/<int:booking_id>', methods=['POST'])
@login_required
def user_cancel_booking(booking_id):
    try:
        conn = get_database_connection()
        cursor = conn.cursor()
        
        # Update booking status to cancelled
        cursor.execute("""
            UPDATE bookings 
            SET status = 'cancelled' 
            WHERE id = %s AND user_id = %s
        """, (booking_id, session['user_id']))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'error': 'Booking not found or unauthorized'}), 404
            
        conn.commit()
        return jsonify({'success': True, 'message': 'Booking cancelled successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@app.route('/userprofile')
@login_required
def userprofile():
    conn = get_database_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Get user details
        cursor.execute("SELECT * FROM users WHERE id = %s", [session['user_id']])
        user = cursor.fetchone()
        
        # Get recent bookings
        cursor.execute("""
            SELECT b.*, s.name as station_name 
            FROM bookings b 
            JOIN charging_stations s ON b.station_id = s.id 
            WHERE b.user_id = %s 
            ORDER BY b.created_at DESC 
            LIMIT 5
        """, [session['user_id']])
        recent_bookings = cursor.fetchall()
        
        # Get statistics
        cursor.execute("""
            SELECT COUNT(*) as total_bookings, 
                   COALESCE(SUM(total_amount), 0) as total_amount 
            FROM bookings 
            WHERE user_id = %s
        """, [session['user_id']])
        stats = cursor.fetchone()
        
        return render_template('userprofile.html', 
                             user=user, 
                             recent_bookings=recent_bookings, 
                             stats=stats)
    finally:
        cursor.close()
        conn.close()
    
    return render_template('user_profile.html')

UPLOAD_FOLDER = 'static/profile_photos'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload_profile_photo', methods=['POST'])
@login_required
def upload_profile_photo():
    try:
        if 'photo' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        file = request.files['photo']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        if file and allowed_file(file.filename):
            # Create unique filename
            filename = secure_filename(f"user_{session['user_id']}_{file.filename}")
            filepath = os.path.join(app.root_path, UPLOAD_FOLDER, filename)
            
            # Save file
            file.save(filepath)
            
            # Update database
            conn = get_database_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET profile_photo = %s WHERE id = %s", 
                         [filename, session['user_id']])
            conn.commit()
            cursor.close()
            conn.close()
            
            return jsonify({'success': True})
        
        return jsonify({'success': False, 'error': 'Invalid file type'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/booking_details')
@login_required
def booking_details():
    conn = get_database_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT b.*, s.name as station_name, s.address, s.latitude, s.longitude
        FROM bookings b
        JOIN charging_stations s ON b.station_id = s.id
        WHERE b.user_id = %s
        ORDER BY b.created_at DESC
    """, (session['user_id'],))
    
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('booking_details.html', bookings=bookings)



@app.route('/user/finish-charging/<int:booking_id>', methods=['POST'])
@login_required
def user_finish_charging(booking_id):
    try:
        conn = get_database_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE bookings 
            SET status = 'Finished' 
            WHERE id = %s AND user_id = %s
        """, (booking_id, session['user_id']))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'error': 'Booking not found or unauthorized'}), 404
            
        conn.commit()
        return jsonify({'success': True, 'message': 'Charging completed successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@app.route('/api/admin/stations/<int:station_id>', methods=['GET'])
@admin_required
def get_admin_station(station_id):
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, name, address, district, latitude, longitude,
                   connector_type, charging_speed, power_rating,
                   status, price_per_hour
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

@app.route('/api/admin/stations/<int:station_id>', methods=['PUT'])
@admin_required
def update_station(station_id):
    try:
        data = request.json
        conn = get_database_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE charging_stations 
            SET name = %s, address = %s, district = %s,
                latitude = %s, longitude = %s,
                connector_type = %s, charging_speed = %s,
                power_rating = %s, status = %s,
                price_per_hour = %s
            WHERE id = %s
        """, (
            data['name'],
            data['address'],
            data['district'],
            data['latitude'],
            data['longitude'],
            data['connector_type'],
            data['charging_speed'],
            data['power_rating'],
            data['status'],
            data['price_per_hour'],
            station_id
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Station updated successfully'
        })
        
    except Exception as e:
        print(f"Error updating station: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/admin/stations/<int:station_id>', methods=['DELETE'])
@admin_required
def delete_station(station_id):
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        # First check if there are any bookings for this station
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM bookings 
            WHERE station_id = %s
        """, (station_id,))
        
        booking_count = cursor.fetchone()['count']
        
        if booking_count > 0:
            # Delete associated bookings first
            cursor.execute("DELETE FROM bookings WHERE station_id = %s", (station_id,))
        
        # Now delete the station
        cursor.execute("DELETE FROM charging_stations WHERE id = %s", (station_id,))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Station and associated bookings deleted successfully'
        })
        
    except Exception as e:
        print(f"Error deleting station: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Around line 900-930, keep only ONE admin_profile route:
@app.route('/admin/profile')
@admin_required
def admin_profile():
    try:
        conn = get_database_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Modified query to fetch admin user
        cursor.execute("""
            SELECT id, full_name, email, created_at, profile_photo 
            FROM users 
            WHERE email = 'admin@gmail.com'
        """)
        
        admin = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not admin:
            flash('Admin profile not found', 'error')
            return redirect(url_for('admin_dashboard'))
            
        return render_template('admin_profile.html', admin=admin)
        
    except Exception as e:
        print(f"Error loading admin profile: {e}")  # Add debug print
        flash('Error loading profile: ' + str(e), 'error')
        return redirect(url_for('admin_dashboard'))

# Fix the update_admin_profile function around line 950:
@app.route('/admin/profile/update', methods=['POST'])
@admin_required
def update_admin_profile():
    try:
        conn = get_database_connection()
        cursor = conn.cursor()
        
        # Handle file upload
        if 'profile_photo' in request.files:
            file = request.files['profile_photo']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"admin_{session['user_id']}_{file.filename}")
                file.save(os.path.join(app.root_path, UPLOAD_FOLDER, filename))
                
                cursor.execute("""
                    UPDATE users 
                    SET profile_photo = %s 
                    WHERE id = %s
                """, (filename, session['user_id']))
        
        # Update basic info without phone_number
        cursor.execute("""
            UPDATE users 
            SET full_name = %s, email = %s
            WHERE id = %s
        """, (
            request.form['full_name'],
            request.form['email'],
            session['user_id']
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Profile updated successfully', 'success')
        return redirect(url_for('admin_profile'))
        
    except Exception as e:
        flash('Error updating profile: ' + str(e), 'error')
        return redirect(url_for('admin_profile'))

if __name__ == '__main__':
    app.run(debug=True)
    