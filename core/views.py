from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count
from django.contrib import messages
from .models import Question, Submission

def index(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('admin:index')
        return redirect('dashboard')
    return render(request, 'index.html')

@login_required
def dashboard(request):
    if request.user.is_staff:
        return redirect('admin:index')
    
    questions = Question.objects.all()
    user_submissions = {s.question_id: s for s in Submission.objects.filter(user=request.user)}
    return render(request, 'dashboard.html', {
        'questions': questions,
        'user_submissions': user_submissions
    })

@login_required
def submit_answer(request, question_id):
    if request.method == 'POST':
        question = get_object_or_404(Question, id=question_id)
        answer = request.POST.get('answer')
        
        submission, created = Submission.objects.update_or_create(
            user=request.user,
            question=question,
            defaults={'answer': answer}
        )
        
        if created:
            messages.success(request, 'Answer submitted successfully!')
        else:
            messages.success(request, 'Submission updated!')
            
    return redirect('dashboard')

@login_required
def leaderboard(request):
    rankings = User.objects.filter(is_staff=False).annotate(
        score=Count('submissions')
    ).order_by('-score')
    
    return render(request, 'leaderboard.html', {'rankings': rankings})
