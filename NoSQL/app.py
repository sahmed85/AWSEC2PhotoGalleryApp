#!flask/bin/python
import sys, os
sys.path.append(os.path.abspath(os.path.join('..', 'utils')))
from env import AWS_ACCESS_KEY, AWS_SECRET_ACCESS_KEY, AWS_REGION, PHOTOGALLERY_S3_BUCKET_NAME, DYNAMODB_TABLE, DYNAMODB_USERTABLE, SERVER_HOSTNAME
from flask import Flask, jsonify, abort, request, make_response, url_for
from flask import render_template, redirect
from flask import session, escape
import time
import exifread
import json
import uuid
import boto3
from boto3.dynamodb.conditions import Key, Attr
from boto3.dynamodb.types import Binary
from botocore.exceptions import ClientError
import bcrypt  
import shortuuid
import pymysql.cursors
from datetime import datetime, timedelta
import pytz
from pytz import timezone
from itsdangerous import URLSafeTimedSerializer


app = Flask(__name__, static_url_path="")
#Flask session data secret key
app.secret_key = '8Qs8yijqeXtPIxd'
#Set the lifetime of the session before prompting relogin for 10min
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
#bcrypt salt, randomly generated using bcrypt.gensalt()
bcrypt_salt = b'$2b$12$SVKewoTf80SCXW/iZoRbLu'
#token gen salt is same as bcrypt (not best pratice but for testing only)
token_salt = b'$2b$12$SVKewoTf80SCXW/iZoRbLu'
# hostname of the server
server_hostname = SERVER_HOSTNAME

dynamodb = boto3.resource('dynamodb', aws_access_key_id=AWS_ACCESS_KEY,
                            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                            region_name=AWS_REGION)

table = dynamodb.Table(DYNAMODB_TABLE)
usertable = dynamodb.Table(DYNAMODB_USERTABLE)

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

# this functon will check if the user supplied email and password is correct and authenticated
def validate_user(email,password):
    # check the user DB to see if this user exits or not
    # this function will also check if the user exits and authenticated
    try:
        # use get_item to see if a user is 
        response = usertable.get_item(
            Key={
                'email': email
            }
        )
        # print(response)
        # check if empty
        if 'Item' not in response:
            return False
        else:
            if(response['Item']['authenticated'] == False):
                # return to the user that their account is not authenticated
                abort(401)
            else:
                # check if the user password is equal to the one in the DB
                encoded_password = bytes(password,'utf-8')
                # print(response['Item'])
                # print("DATA TYPE IS in Reading:\n")
                # print(type(response['Item']['password']))
                # print(type(response['Item']['password'].value.decode('utf-8')))
                encoded_hashPassword = bytes(response['Item']['password'].value.decode('utf-8'), 'utf-8')
                #encoded_hashPassword = response['Item']['password']
                if(bcrypt.checkpw(encoded_password,encoded_hashPassword)):
                    return True
                else:
                    return False
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False


# this function checks if the email is already in use 
def checkUserExists(email):
    try:
        # use get_item to see if the email already exists
        # remember that Primary Keys in DynamoDB is unique
        response = usertable.get_item(
            Key={
                'email': email
            }
        )
        # check if empty
        if 'Item' not in response:
            # if empty return that it is false, the user doesn't exist
            return False
        else:
            # if not empty, the user already exists
            return True
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False

       
# this function inserts a new user into DynamoDB user table
def insert_newUser(firstname,lastname,email,hash_password):
    try:
        #use put_item to put the new user into the DB
        response = usertable.put_item(
            Item={
                'email': email,
                'uuid': str(uuid.uuid4()),
                'password': hash_password,
                'fname': firstname,
                'lname': lastname,
                'authenticated': False
            }
        )
    except ClientError as e:
        print(e.response['Error']['Message'])


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
        # Generate the token to send to email
        token = create_confirmToken(email)
        # Provide the contents of the email.
        response = ses.send_email(
        Destination={
            'ToAddresses': [RECEIVER],
        },
        Message={
            'Body': {
                'Text': {
                    'Data': 'Hi, I’m sending this confirm your account creation in the Photo Gallery App. Please follow this link:' + server_hostname + '/confirm/' + token,
                },
            },
            'Subject': {
                'Data': 'Confirmation Token Photo Gallery App'
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

# this function will create a confirmation token which the email function will call
def create_confirmToken(email):
    #utlize the same secret key as app session (probably not best practice but makes easier for testing)
    serializer = URLSafeTimedSerializer(app.secret_key)
    token = serializer.dumps(email,salt=token_salt)
    return token

# this function will check if token equals to email and not expired
def check_confirmToken(token):
    # de-encode the token recevied from user and check if email is equal
    try:
        serializer = URLSafeTimedSerializer(app.secret_key)
        token_email = serializer.loads(token,salt=token_salt,max_age=600)
        if(checkUserExists(token_email)):
            # if true, then we can set the auth column to true
            if(update_UserAuth(token_email)):
                return True
            else:
                return False
        else: 
            return False
    except Exception as e:
        print(e)
        print('expired token')

# this function will run a query to update the auth attribute in DynamoDB for the user
def update_UserAuth(email):
    # use the update_item function to update the Auth attribute.
    try:
        response = usertable.update_item(
            Key={
                'email': email
            },
            UpdateExpression="set authenticated =:f",
            ExpressionAttributeValues={
                ':f': True
            }
        )
        return True
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False

# this function will update the photo info
def updatePhoto(albumID,photoID,title,description,tags):
    # run update_tem function to update the entry
    try:
        response = table.update_item(
            Key={
                'albumID': albumID,
                'photoID': photoID
            },
            UpdateExpression="set title=:t, description=:d,tags=:a",
            ExpressionAttributeValues={
                ':t': title,
                ':d': description,
                ':a': tags
            }
        )
        return True
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False

# this function will delete a photo 
def deletePhoto(albumID,photoID):
    try:
        # run the delete_item function to delete the entry
        photo_response = table.delete_item(
            Key={
                'albumID': albumID,
                'photoID': photoID
            }
        )
        return True
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False

# this function will delete a album
def deleteAlbum(albumID):
    try:
        # before we delete the album we need to delete all the pictures associated with it
        albumResponse = table.query(KeyConditionExpression=Key('albumID').eq(albumID))
        albumMeta = albumResponse['Items']
        print(albumMeta)
        for item in albumMeta:
            # delete all items in this query
            # it will delete the photos and album entries
            response = table.delete_item(
                Key={
                    'albumID': item['albumID'],
                    'photoID': item['photoID']
                }
            )
        return True
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False

# this function will delete a user
# when deleting user we need all the albums and photos to be deleted for that user
def deleteUser(email):
    try:
        response = table.scan(FilterExpression=Attr('photoID').eq("thumbnail") & Attr('email').eq(email))
        results = response['Items']
        # now we have all the album, so we can call deleteAlbum in a loop to delete all of them
        for item in results:
            if(not deleteAlbum(item['albumID'])):
                return False
        # now delete the user entry in the user table
        usertable_response = usertable.delete_item(
            Key={
                'email': email
            }
        )
        return True
    except ClientError as e:
        print(e.response['Error']['Message'])
        return False
                
        



###############################################################################################################
# Application Handling

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
    return render_template('login.html', login_status = "Your account has not been verified. Please check your email!")

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
            return render_template('login.html', login_status = 'Incorrect Username or Password. Try again!')
    else:
        #return the login page temple
        return render_template('login.html', login_status = 'Please login using your email and password.')


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
                #user_hashed_password = str(user_hashed_password)
                # print("DATA TYPE IS in Creation: \n")
                # print(type(user_hashed_password))
                insert_newUser(user_fname,user_lname,user_email,user_hashed_password)
                send_confirmEmail(user_email)
                return render_template('login.html', login_status = 'Account created! Please verify your account from your email.')
            else:
                #return an error that the user already exists
                return make_response(jsonify({'error': 'User Already Exists'}), 400)
    else:
        return render_template('signup.html')


# app route for confirmation from email
@app.route('/confirm/<string:tokenID>', methods=['GET'])
def confirm_page(tokenID):
    #GET request with the token passed in needs to be confirmed
    user_token = tokenID
    if(check_confirmToken(user_token)):
        # If token is correct and table is updated then redirect user to login page
        return render_template('login.html', login_status = "Account confirmed! Please login using your email and password.")
    else:
        abort(404)


# app route for deleting the User account
@app.route('/deleteaccount', methods=['GET'])
def delete_page():
    # GET request for deleting account from top navigation
    # session already stores the user email so we can use that to traverse the delete users data
    if(deleteUser(session['email'])):
        # if this function returns true, destroy the session and then navigate to the login page
        session.pop('email', default=None)
        return redirect(url_for('login_page'))
    else:
        return make_response(jsonify({'error': 'Bad request'}), 400)




@app.route('/', methods=['GET'])
def home_page():
    """ Home page route.

    get:
        description: Endpoint to return home page.
        responses: Returns all the albums.
    """
    if 'email' in session:
        response = table.scan(FilterExpression=Attr('photoID').eq("thumbnail") & Attr('email').eq(session['email']))
        results = response['Items']

        if len(results) > 0:
            for index, value in enumerate(results):
                createdAt = datetime.strptime(str(results[index]['createdAt']), "%Y-%m-%d %H:%M:%S")
                createdAt_UTC = pytz.timezone("UTC").localize(createdAt)
                results[index]['createdAt'] = createdAt_UTC.astimezone(pytz.timezone("US/Eastern")).strftime("%B %d, %Y")

        return render_template('index.html', albums=results)
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

                createdAtlocalTime = datetime.now().astimezone()
                createdAtUTCTime = createdAtlocalTime.astimezone(pytz.utc)

                table.put_item(
                    Item={
                        "albumID": str(albumID),
                        "photoID": "thumbnail",
                        "name": name,
                        "description": description,
                        "thumbnailURL": uploadedFileURL,
                        "createdAt": createdAtUTCTime.strftime("%Y-%m-%d %H:%M:%S"),
                        "email": session['email']
                    }
                )

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
        albumResponse = table.query(KeyConditionExpression=Key('albumID').eq(albumID) & Key('photoID').eq('thumbnail'))
        albumMeta = albumResponse['Items']

        response = table.scan(FilterExpression=Attr('albumID').eq(albumID) & Attr('photoID').ne('thumbnail') & Attr('email').eq(session['email']))
        items = response['Items']

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
                ExifDataStr = json.dumps(ExifData)

                createdAtlocalTime = datetime.now().astimezone()
                updatedAtlocalTime = datetime.now().astimezone()

                createdAtUTCTime = createdAtlocalTime.astimezone(pytz.utc)
                updatedAtUTCTime = updatedAtlocalTime.astimezone(pytz.utc)

                table.put_item(
                    Item={
                        "albumID": str(albumID),
                        "photoID": str(photoID),
                        "title": title,
                        "description": description,
                        "tags": tags,
                        "photoURL": uploadedFileURL,
                        "EXIF": ExifDataStr,
                        "createdAt": createdAtUTCTime.strftime("%Y-%m-%d %H:%M:%S"),
                        "updatedAt": updatedAtUTCTime.strftime("%Y-%m-%d %H:%M:%S"),
                        "email": session['email']
                    }
                )

            return redirect(f'''/album/{albumID}''')

        else:

            albumResponse = table.query(KeyConditionExpression=Key('albumID').eq(albumID) & Key('photoID').eq('thumbnail'))
            albumMeta = albumResponse['Items']

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
        albumResponse = table.query(KeyConditionExpression=Key('albumID').eq(albumID) & Key('photoID').eq('thumbnail'))
        albumMeta = albumResponse['Items']

        response = table.query( KeyConditionExpression=Key('albumID').eq(albumID) & Key('photoID').eq(photoID))
        results = response['Items']

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

            createdAt_UTC = pytz.timezone("UTC").localize(createdAt)
            updatedAt_UTC = pytz.timezone("UTC").localize(updatedAt)

            photo['createdAt']=createdAt_UTC
            photo['updatedAt']=updatedAt_UTC
            
            tags=photo['tags'].split(',')
            exifdata=photo['EXIF']
            
            return render_template('photodetail.html', photo=photo, tags=tags, exifdata=exifdata, albumID=albumID, albumName=albumMeta[0]['name'])
        else:
            return render_template('photodetail.html', photo={}, tags=[], exifdata={}, albumID=albumID, albumName="")


# this route will allow user to update their photo information
@app.route('/album/<string:albumID>/editphoto.html/<string:photoID>', methods=['GET','POST'])
def editphoto_page(albumID,photoID):
    if 'email' in session:
        # handle request type
        if(request.method == 'POST'):
            #handle the form inputs
            new_title = request.form['newTitle']
            new_description = request.form['newDescription']
            new_tags = request.form['newTags']
            if(updatePhoto(albumID,photoID,new_title,new_description,new_tags)):
                return redirect('/album/' + albumID+'/photo/' + photoID)
            else:
                return make_response(jsonify({'error': 'Bad request'}), 400)
        else:
            return render_template('editphoto.html',photoID = photoID, albumID = albumID)
    else:
        return redirect(url_for('login_page'))



# this route will allow user to delete their album and subsequently delete the photos
# it is bad practice to make this delete functionality a GET but I am a bit lazy      
@app.route('/album/deleteAlbum/<string:albumID>', methods=['GET'])
def deleteAlbum_page(albumID):
    if 'email' in session:
        #handle the GET request; Remember this bad practice in general, we should make this a DELETE request handle
        if(deleteAlbum(albumID)):
            #deleted album 
            return redirect('/')
        else:
            return make_response(jsonify({'error': 'Bad request'}), 400)
    else:
        return redirect(url_for('login_page'))    


# this route will allow user to delete their photo
# it is bad practice to make this delete functionality a GET but I am a bit lazy 
@app.route('/album/<string:albumID>/deletephoto/<string:photoID>', methods=['GET'])
def deletephoto_page(albumID,photoID):
    if 'email' in session:
        #handle the GET request; Remember this bad practice in general, we should make this a DELETE request handle
        if(deletePhoto(albumID,photoID)):
            # deleted photo successfully
            return redirect('/album/' + albumID)
        else:
            return make_response(jsonify({'error': 'Bad request'}), 400)
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

        response = table.scan(FilterExpression=Attr('name').contains(query) | Attr('description').contains(query) & Attr('email').eq(session['email']))
        results = response['Items']

        items=[]
        for item in results:
            if item['photoID'] == 'thumbnail':
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

        response = table.scan(FilterExpression=Attr('title').contains(query) | Attr('description').contains(query) | Attr('tags').contains(query) | Attr('EXIF').contains(query) & Attr('email').eq(session['email']))
        results = response['Items']

        items=[]
        for item in results:
            if item['photoID'] != 'thumbnail' and item['albumID'] == albumID:
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
