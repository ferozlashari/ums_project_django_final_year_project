#!/usr/bin/env bash
set -e
if [ ! -d venv ]; then python3 -m venv venv; fi
source venv/bin/activate
pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
python manage.py migrate
python manage.py seed_roles
python manage.py check
echo "Setup complete. Create an administrator with: python manage.py createsuperuser"
python manage.py runserver
