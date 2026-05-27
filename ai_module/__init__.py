import os
from flask import Blueprint

# Initialize the blueprint for the AI additive module.
# Setting template_folder and static_folder relative to this directory.
ai_blueprint = Blueprint(
    'ai',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='static'
)

# Import routes to register endpoints
from ai_module import routes
