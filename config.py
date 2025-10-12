# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.getenv('SQLALCHEMY_DATABASE_URI') or os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'images')

    # Debug print statements
    print("Loaded DB URI:", os.getenv("DATABASE_URL"))
    print("Loaded UPLOAD_FOLDER:", UPLOAD_FOLDER)

# Commented-out version 1
#import os
#from dotenv import load_dotenv

#load_dotenv()

#class Config:
#    SQLALCHEMY_DATABASE_URI = (
#        f"mysql+pymysql://{os.getenv('DB_USERNAME')}:{os.getenv('DB_PASSWORD')}@"
#        f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
#    )
#    SQLALCHEMY_TRACK_MODIFICATIONS = False
#    SECRET_KEY = os.environ.get('SECRET_KEY')

## `config.py`

#import os
#from dotenv import load_dotenv

#load_dotenv()

#class Config:
#    SECRET_KEY = os.getenv('SECRET_KEY')
#    SQLALCHEMY_DATABASE_URI = (
#        f"mysql+pymysql://{os.getenv('MYSQL_USER')}:"
#        f"{os.getenv('MYSQL_PASSWORD')}@"
#        f"{os.getenv('MYSQL_HOST')}/"
#        f"{os.getenv('MYSQL_DB')}"
#    )
#    SQLALCHEMY_TRACK_MODIFICATIONS = False
#    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'images')

#class Config:
#    SECRET_KEY = os.getenv("SECRET_KEY")
#    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
#    SQLALCHEMY_TRACK_MODIFICATIONS = False
#    GOOGLE_MAPS_API_KEY = os.getenv("AIzaSyDYURPPj9xzbF6elY_xKfNH8AMPahTQtpA")
#    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static/images/')

#app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static/images/')
#print("Loaded DB URI:", os.getenv("DATABASE_URL"))