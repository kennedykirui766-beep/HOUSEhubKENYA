import os
from models.models import House 
from extensions import db 
for house in House.query.all(): 
    if house.image_urls and ('\\static\\images\\' in house.image_urls or '/static/images' in house.image_urls): 
        house.image_urls = ','.join([os.path.basename(f.replace('\\', '/')) for f in house.image_urls.split(',')]) 
        db.session.commit() 
print("Updated image_urls in database.") 
