from django.contrib import admin
from .models import User, Api, Chat, Setting

admin.site.register(User)
admin.site.register(Api)
admin.site.register(Chat)
admin.site.register(Setting)