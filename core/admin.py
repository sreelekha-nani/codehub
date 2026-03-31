from django.contrib import admin
from .models import Question, Submission

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('title', 'answer')

@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('user', 'question', 'created_at')
    list_filter = ('question', 'user')
