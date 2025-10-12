import os

def house_to_dict(house):
    return {
        'id': house.id,
        'title': house.title,
        'description': house.description,
        'location': house.location,
        'lat': house.lat,
        'lng': house.lng,
        'category': house.category,
        'image_urls': [os.path.basename(url) for url in (house.image_urls.split(',') if house.image_urls else [])]
    }