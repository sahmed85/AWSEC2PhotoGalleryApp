#!flask/bin/python
import sys, os
sys.path.append(os.path.abspath(os.path.join('..', 'utils')))
from env import AWS_ACCESS_KEY, AWS_SECRET_ACCESS_KEY, AWS_REGION, PHOTOGALLERY_S3_BUCKET_NAME, RDS_DB_HOSTNAME, RDS_DB_USERNAME, RDS_DB_PASSWORD, RDS_DB_NAME
from flask import Flask, jsonify, abort, request, make_response, url_for
from flask import render_template, redirect
from flask import session, escape
import time
import exifread
import json
import uuid
import boto3
from botocore.exceptions import ClientError
import bcrypt  
import shortuuid
import pymysql.cursors
from datetime import datetime, timedelta
from pytz import timezone

"""
    INSERT NEW LIBRARIES HERE (IF NEEDED)
"""





"""
"""

app = Flask(__name__, static_url_path="")
#Flask session data secrect key
app.secret_key = '8Qs8yijqeXtPIxd'
#Set the lifetime of the session before prompting relogin for 10min
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=1)
#bcrypt salt, randomly generated using bcrypt.gensalt()
bcrypt_salt = b'$2b$12$SVKewoTf80SCXW/iZoRbLu'

UPLOAD_FOLDER = os.path.join(app.root_path,'static','media')
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg'])

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def getExifData(path_name):
    f = open(path_name, 'rb')
    tags = exifread.process_file(f)
    ExifData={}
    for tag in tags.keys():
        if tag not in ('JPEGThumbnail', 'TIFFThumbnail', 'Filename', 'EXIF MakerNote'):
            key="%s"%(tag)
            val="%s"%(tags[tag])
            ExifData[key]=val
    return ExifData


def s3uploading(filename, filenameWithPath, uploadType="photos"):
    s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY,
                            aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
                       
    bucket = PHOTOGALLERY_S3_BUCKET_NAME
    path_filename = uploadType + "/" + filename

    s3.upload_file(filenameWithPath, bucket, path_filename)  
    s3.put_object_acl(ACL='public-read', Bucket=bucket, Key=path_filename)
    return f'''http://{PHOTOGALLERY_S3_BUCKET_NAME}.s3.amazonaws.com/{path_filename}'''

def get_database_connection():
    conn = pymysql.connect(host=RDS_DB_HOSTNAME,
                             user=RDS_DB_USERNAME,
                             password=RDS_DB_PASSWORD,
                             db=RDS_DB_NAME,
                             charset='utf8mb4',
                             cursorclass=pymysql.cursors.DictCursor)
    return conn

def send_email(email, body):
    try:
        ses = boto3.client('ses', aws_access_key_id=AWS_ACCESS_KEY,
                                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                                region_name=REGION)
        ses.send_email(
            Source=os.getenv('SES_EMAIL_SOURCE'),
            Destination={'ToAddresses': [email]},
            Message={
                'Subject': {'Data': 'Photo Gallery: Confirm Your Account'},
                'Body': {
                    'Text': {'Data': body}
                }
            }
        )

    except ClientError as e:
        print(e.response['Error']['Message'])

        return False
    else:
        print("Email sent! Message ID:"),
        print(response['MessageId'])

        return True

def validate_user(email,password):
    # connect to the DB and validate user credentials in user table
    try:
        validate_conn = get_database_connection()
        cursor = validate_conn.cursor()
        cursor.execute("SELECT * FROM photogallerydb.User WHERE email="+"'"+email+ "'" + ";")
        results = cursor.fetchone()
        validate_conn.close()
        # if the result is empty, it means that user email in not in the DB
        if(cursor.rowcount == 0):
            return False
        encoded_password = bytes(password, 'utf-8')
        encoded_hashPassword = bytes(results['password'], 'utf-8')
        if(bcrypt.checkpw(encoded_password,encoded_hashPassword)):
            return True
        else:
            return False
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False

# this functions checks if the email is already in use
def checkUserExists(email):
    # connect to the DB and check if email exists in DB
    try:
        validate_conn = get_database_connection()
        cursor = validate_conn.cursor()
        cursor.execute("SELECT * FROM photogallerydb.User WHERE email="+"'"+email+ "'" + ";")
        results = cursor.fetchone()
        validate_conn.close()
        # if the result is empty, it means that user email in not in the DB
        if(cursor.rowcount == 0):
            return False
        else:
            return True
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False

# this function inserts a new user into the DB
def insert_newUser(firstname,lastname,email,hash_password):
    # connect to the DB and check if email exists in DB
    try:
        validate_conn = get_database_connection()
        cursor = validate_conn.cursor()
        insertStatement = "INSERT INTO `photogallerydb`.`User` (`userID`, `email`, `firstName`, `lastName`, `password`, `authenticated`) VALUES (uuid_short(),%s,%s,%s,%s,TRUE)"
        cursor.execute(insertStatement,(email,firstname,lastname,hash_password))
        validate_conn.commit()
        validate_conn.close()
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False

# this function will send an email to user from signup to verify account
def send_confirmEmail(email):
    # Create a new SES resource and specify a region
    ses = boto3.client('ses',
                        region_name = 'us-east-1', 
                        aws_access_key_id=AWS_ACCESS_KEY,
                        aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
    SENDER = 'sahmed85@gatech.edu'
    RECEIVER = email
    # Try to send the email.
    try:
        #Provide the contents of the email.
        response = ses.send_email(
        Destination={
            'ToAddresses': [RECEIVER],
        },
        Message={
            'Body': {
                'Text': {
                    'Data': 'This is an email from AWS SES',
                },
            },
            'Subject': {
                'Data': 'Hi, I’m sending this email from AWS SES'
            },
         },
         Source=SENDER
        )
    # Display an error if something goes wrong.
    except ClientError as e:
        print(e.response['Error']['Message'])
    else:
        print("Email sent! Message ID:"),
        print(response['MessageId'])

@app.errorhandler(400)
def bad_request(error):
    """ 400 page route.

    get:
        description: Endpoint to return a bad request 400 page.
        responses: Returns 400 object.
    """
    return make_response(jsonify({'error': 'Bad request'}), 400)



@app.errorhandler(404)
def not_found(error):
    """ 404 page route.

    get:
        description: Endpoint to return a not found 404 page.
        responses: Returns 404 object.
    """
    return make_response(jsonify({'error': 'Not found'}), 404)

@app.errorhandler(401)
def unauthenticaed(error):
    return render_template('login.html', login_status = False)

# app route for the login page
@app.route('/login', methods=['GET','POST'])
def login_page():
    # Login Page route
    if request.method == 'POST':
        #handle the login parameters
        user_email = request.form['username']
        user_password = request.form['password']
        if(validate_user(user_email,user_password)):
            session['email'] = user_email
            return redirect(url_for('home_page'))
        else:
            abort(401)
    else:
        #return the login page temple
        return render_template('login.html', login_status = True)

# app route for sign up page
@app.route('/signup', methods=['GET', 'POST'])
def signup_page():
    # Signup Page POST, add entry to DB and trigger email confirmation
    if request.method == 'POST':
        #handle the form and add to DB and trigger email confirmation
        user_fname = request.form['firstname']
        user_lname = request.form['lastname']
        user_email = request.form['email']
        user_password = request.form['password']
        user_rpassword = request.form['password1']
        if(user_password != user_rpassword):
            #return an error that the passwords don't match
            return make_response(jsonify({'error': 'Passwords Do Not Match'}), 400)
        else:
            # check if email exists already
            if(checkUserExists(user_email) == False):
                #add new user to DB and hash password using bcrypt
                encoded_password = bytes(user_password, 'utf-8')
                user_hashed_password = bcrypt.hashpw(encoded_password,bcrypt_salt)
                insert_newUser(user_fname,user_lname,user_email,user_hashed_password)
                send_confirmEmail(user_email)
                return render_template('login.html', login_status = True)
            else:
                #return an error that the user already exists
                return make_response(jsonify({'error': 'User Already Exists'}), 400)
    else:
        return render_template('signup.html')

@app.route('/', methods=['GET'])
def home_page():
    """ Home page route.

    get:
        description: Endpoint to return home page.
        responses: Returns all the albums.
    """
    if 'email' in session:
        conn=get_database_connection()
        cursor = conn.cursor ()
        cursor.execute("SELECT * FROM photogallerydb.Album;")
        results = cursor.fetchall()
        conn.close()
        
        items=[]
        for item in results:
            album={}
            album['albumID'] = item['albumID']
            album['name'] = item['name']
            album['description'] = item['description']
            album['thumbnailURL'] = item['thumbnailURL']

            createdAt = datetime.strptime(str(item['createdAt']), "%Y-%m-%d %H:%M:%S")
            createdAt_UTC = timezone("UTC").localize(createdAt)
            album['createdAt']=createdAt_UTC.astimezone(timezone("US/Eastern")).strftime("%B %d, %Y")

            items.append(album)

        return render_template('index.html', albums=items)
    else:
        return redirect(url_for('login_page'))



@app.route('/createAlbum', methods=['GET', 'POST'])
def add_album():
    """ Create new album route.

    get:
        description: Endpoint to return form to create a new album.
        responses: Returns all the fields needed to store new album.

    post:
        description: Endpoint to send new album.
        responses: Returns user to home page.
    """
    if 'email' in session:
        if request.method == 'POST':
            uploadedFileURL=''
            file = request.files['imagefile']
            name = request.form['name']
            description = request.form['description']

            if file and allowed_file(file.filename):
                albumID = uuid.uuid4()
                
                filename = file.filename
                filenameWithPath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filenameWithPath)
                
                uploadedFileURL = s3uploading(str(albumID), filenameWithPath, "thumbnails");

                conn=get_database_connection()
                cursor = conn.cursor ()
                statement = f'''INSERT INTO photogallerydb.Album (albumID, name, description, thumbnailURL) VALUES ("{albumID}", "{name}", "{description}", "{uploadedFileURL}");'''
                
                result = cursor.execute(statement)
                conn.commit()
                conn.close()

            return redirect('/')
        else:
            return render_template('albumForm.html')
    else:
        return redirect(url_for('login_page'))



@app.route('/album/<string:albumID>', methods=['GET'])
def view_photos(albumID):
    """ Album page route.

    get:
        description: Endpoint to return an album.
        responses: Returns all the photos of a particular album.
    """
    if 'email' in session:
        conn=get_database_connection()
        cursor = conn.cursor ()
        # Get title
        statement = f'''SELECT * FROM photogallerydb.Album WHERE albumID="{albumID}";'''
        cursor.execute(statement)
        albumMeta = cursor.fetchall()
        
        # Photos
        statement = f'''SELECT photoID, albumID, title, description, photoURL FROM photogallerydb.Photo WHERE albumID="{albumID}";'''
        cursor.execute(statement)
        results = cursor.fetchall()
        conn.close() 
        
        items=[]
        for item in results:
            photos={}
            photos['photoID'] = item['photoID']
            photos['albumID'] = item['albumID']
            photos['title'] = item['title']
            photos['description'] = item['description']
            photos['photoURL'] = item['photoURL']
            items.append(photos)

        return render_template('viewphotos.html', photos=items, albumID=albumID, albumName=albumMeta[0]['name'])
    else:
        return redirect(url_for('login_page'))



@app.route('/album/<string:albumID>/addPhoto', methods=['GET', 'POST'])
def add_photo(albumID):
    """ Create new photo under album route.

    get:
        description: Endpoint to return form to create a new photo.
        responses: Returns all the fields needed to store a new photo.

    post:
        description: Endpoint to send new photo.
        responses: Returns user to album page.
    """
    if 'email' in session:
        if request.method == 'POST':    
            uploadedFileURL=''
            file = request.files['imagefile']
            title = request.form['title']
            description = request.form['description']
            tags = request.form['tags']

            if file and allowed_file(file.filename):
                photoID = uuid.uuid4()
                filename = file.filename
                filenameWithPath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filenameWithPath)            
                
                uploadedFileURL = s3uploading(filename, filenameWithPath);
                
                ExifData=getExifData(filenameWithPath)

                conn=get_database_connection()
                cursor = conn.cursor ()
                ExifDataStr = json.dumps(ExifData)
                statement = f'''INSERT INTO photogallerydb.Photo (PhotoID, albumID, title, description, tags, photoURL, EXIF) VALUES ("{photoID}", "{albumID}", "{title}", "{description}", "{tags}", "{uploadedFileURL}", %s);'''
                
                result = cursor.execute(statement, (ExifDataStr,))
                conn.commit()
                conn.close()

            return redirect(f'''/album/{albumID}''')
        else:
            conn=get_database_connection()
            cursor = conn.cursor ()
            # Get title
            statement = f'''SELECT * FROM photogallerydb.Album WHERE albumID="{albumID}";'''
            cursor.execute(statement)
            albumMeta = cursor.fetchall()
            conn.close()

            return render_template('photoForm.html', albumID=albumID, albumName=albumMeta[0]['name'])
    else:
        return redirect(url_for('login_page'))



@app.route('/album/<string:albumID>/photo/<string:photoID>', methods=['GET'])
def view_photo(albumID, photoID):  
    """ photo page route.

    get:
        description: Endpoint to return a photo.
        responses: Returns a photo from a particular album.
    """ 
    if 'email' in session:
        conn=get_database_connection()
        cursor = conn.cursor ()

        # Get title
        statement = f'''SELECT * FROM photogallerydb.Album WHERE albumID="{albumID}";'''
        cursor.execute(statement)
        albumMeta = cursor.fetchall()

        statement = f'''SELECT * FROM photogallerydb.Photo WHERE albumID="{albumID}" and photoID="{photoID}";'''
        cursor.execute(statement)
        results = cursor.fetchall()
        conn.close()

        if len(results) > 0:
            photo={}
            photo['photoID'] = results[0]['photoID']
            photo['title'] = results[0]['title']
            photo['description'] = results[0]['description']
            photo['tags'] = results[0]['tags']
            photo['photoURL'] = results[0]['photoURL']
            photo['EXIF']=json.loads(results[0]['EXIF'])

            createdAt = datetime.strptime(str(results[0]['createdAt']), "%Y-%m-%d %H:%M:%S")
            updatedAt = datetime.strptime(str(results[0]['updatedAt']), "%Y-%m-%d %H:%M:%S")

            createdAt_UTC = timezone("UTC").localize(createdAt)
            updatedAt_UTC = timezone("UTC").localize(updatedAt)

            photo['createdAt']=createdAt_UTC.astimezone(timezone("US/Eastern")).strftime("%B %d, %Y at %-I:%M:%S %p")
            photo['updatedAt']=updatedAt_UTC.astimezone(timezone("US/Eastern")).strftime("%B %d, %Y at %-I:%M:%S %p")
            
            tags=photo['tags'].split(',')
            exifdata=photo['EXIF']
            
            return render_template('photodetail.html', photo=photo, tags=tags, exifdata=exifdata, albumID=albumID, albumName=albumMeta[0]['name'])
        else:
            return render_template('photodetail.html', photo={}, tags=[], exifdata={}, albumID=albumID, albumName="")
    else:
        return redirect(url_for('login_page'))



@app.route('/album/search', methods=['GET'])
def search_album_page():
    """ search album page route.

    get:
        description: Endpoint to return all the matching albums.
        responses: Returns all the albums based on a particular query.
    """ 
    if 'email' in session:
        query = request.args.get('query', None)

        conn=get_database_connection()
        cursor = conn.cursor ()
        statement = f'''SELECT * FROM photogallerydb.Album WHERE name LIKE '%{query}%' UNION SELECT * FROM photogallerydb.Album WHERE description LIKE '%{query}%';'''
        cursor.execute(statement)

        results = cursor.fetchall()
        conn.close()

        items=[]
        for item in results:
            album={}
            album['albumID'] = item['albumID']
            album['name'] = item['name']
            album['description'] = item['description']
            album['thumbnailURL'] = item['thumbnailURL']
            items.append(album)

        return render_template('searchAlbum.html', albums=items, searchquery=query)
    else:
        return redirect(url_for('login_page'))



@app.route('/album/<string:albumID>/search', methods=['GET'])
def search_photo_page(albumID):
    """ search photo page route.

    get:
        description: Endpoint to return all the matching photos.
        responses: Returns all the photos from an album based on a particular query.
    """ 
    if 'email' in session:
        query = request.args.get('query', None)

        conn=get_database_connection()
        cursor = conn.cursor ()
        statement = f'''SELECT * FROM photogallerydb.Photo WHERE title LIKE '%{query}%' AND albumID="{albumID}" UNION SELECT * FROM photogallerydb.Photo WHERE description LIKE '%{query}%' AND albumID="{albumID}" UNION SELECT * FROM photogallerydb.Photo WHERE tags LIKE '%{query}%' AND albumID="{albumID}" UNION SELECT * FROM photogallerydb.Photo WHERE EXIF LIKE '%{query}%' AND albumID="{albumID}";'''
        cursor.execute(statement)

        results = cursor.fetchall()
        conn.close()

        items=[]
        for item in results:
            photo={}
            photo['photoID'] = item['photoID']
            photo['albumID'] = item['albumID']
            photo['title'] = item['title']
            photo['description'] = item['description']
            photo['photoURL'] = item['photoURL']
            items.append(photo)

        return render_template('searchPhoto.html', photos=items, searchquery=query, albumID=albumID)
    else:
        return redirect(url_for('login_page'))



if __name__ == '__main__':
    app.run(debug=True, host="127.0.0.1", port=5000)
