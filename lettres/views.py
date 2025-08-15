from django.middleware.csrf import logger
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg, Count, Q, Case, When, IntegerField
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.db import IntegrityError
from .models import Lettre, Destination, Response, SystemSettings, UserProfile, Rappel
from .forms import LoginForm, LettreForm, ResponseForm, SystemSettingsForm, UserCreationForm, DestinationForm
from datetime import datetime, timedelta
import math
from django.db import IntegrityError
from django.core.exceptions import ValidationError 
from django.urls import reverse
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.conf import settings

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('lettres:dashboard')
            else:
                messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
        else:
            messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
    else:
        form = LoginForm()
    return render(request, 'create_requet/login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('lettres:login')

@login_required
def dashboard(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        if request.user.is_superuser:
            profile = UserProfile.objects.create(user=request.user, role='super_admin')
        else:
            return render(request, 'error.html', {
                'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
            })

    # Redirect admin_reponse and saisie_er to their specific dashboard
    if profile.role in ['admin_reponse', 'saisie_er']:
        return redirect('lettres:dashboard_Reponse')

    # Filter lettres based on role
    lettres = Lettre.objects.all()
    if profile.role == 'saisie_ec':
        lettres = lettres.filter(service=profile.service)  # Restrict to specific service
    elif profile.role == 'admin_saisie':
        lettres = lettres.filter(Q(destinations=profile.destination) | Q(sent_to_all_destinations=True))

    search = request.GET.get('search', '')
    statut_filter = request.GET.get('statut', '')
    categorie_filter = request.GET.get('categorie', '')
    destination_filter = request.GET.get('destination', '')

    if search:
        lettres = lettres.filter(Q(subject__icontains=search) | Q(category__icontains=search))
    if statut_filter:
        lettres = lettres.filter(statut=statut_filter)
    if categorie_filter:
        lettres = lettres.filter(category=categorie_filter)
    if destination_filter:
        lettres = lettres.filter(Q(destinations__id=destination_filter) | Q(sent_to_all_destinations=True))

    lettres_en_attente = lettres.filter(statut='en_attente')
    lettres_repondues = lettres.filter(statut='repondu')
    lettres_en_retard = lettres.filter(statut='en_retard')

    avg_response_time = 0
    responded_lettres = lettres_repondues
    if responded_lettres.exists():
        total_hours = sum(
            (lettre.reponses.first().temps_reponse for lettre in responded_lettres
             if lettre.reponses.exists() and lettre.reponses.first().temps_reponse is not None),
            0
        )
        avg_response_time = total_hours / responded_lettres.count() if responded_lettres.count() > 0 else 0

    today = datetime.now().date()
    lettres_with_progress = []
    for lettre in lettres:
        responded_count = lettre.reponses.filter(statut='repondu').count()
        total_destinations = lettre.destinations.count() if not lettre.sent_to_all_destinations else Destination.objects.count()
        days_overdue = (today - lettre.deadline).days if lettre.deadline and today > lettre.deadline else 0
        days_until_deadline = (lettre.deadline - today).days if lettre.deadline and today <= lettre.deadline else 0
        lettres_with_progress.append({
            'lettre': lettre,
            'responded_count': responded_count,
            'total_destinations': total_destinations,
            'days_overdue': days_overdue,
            'days_until_deadline': days_until_deadline
        })

    total_lettres = lettres.count()

    # Paginate lettres
    paginator = Paginator(lettres_with_progress, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    form = LettreForm() if profile.role in ['super_admin', 'admin_saisie', 'saisie_ec'] else None

    context = {
        'form': form,
        'lettres': page_obj.object_list,
        'page_obj': page_obj,
        'lettres_en_attente': lettres_en_attente,
        'lettres_repondues': lettres_repondues,
        'lettres_en_retard': lettres_en_retard,
        'temps_moyen_reponse': round(avg_response_time, 1),
        'categories': Lettre.objects.values_list('category', flat=True).distinct(),
        'destinations': Destination.objects.all(),
        'search': search,
        'statut_filter': statut_filter,
        'categorie_filter': categorie_filter,
        'destination_filter': destination_filter,
        'user_role': profile.role,
        'total_lettres': total_lettres,
    }
    return render(request, 'create_requet/dashboard.html', context)

@login_required
def dashboard_Reponse(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        logger.error("UserProfile does not exist for user: %s", request.user.username)
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
        })

    if profile.role not in ['admin_reponse', 'saisie_er']:
        logger.error("Unauthorized access to dashboard by user: %s, role: %s", request.user.username, profile.role)
        messages.error(request, "Vous n'êtes pas autorisé à accéder à cette interface.")
        return redirect('lettres:dashboard')

    destination = profile.destination
    if not destination:
        logger.error("No destination for user: %s", request.user.username)
        return render(request, 'user_dashboard.html', {
            'error': 'Aucune destination associée à votre profil.',
            'user_role': profile.role
        })

    responses = Response.objects.filter(destination=destination)
    if profile.role == 'saisie_er':
        responses = responses.filter(lettre__service=profile.service)
    logger.debug("Responses found for user %s: %d", request.user.username, responses.count())

    search = request.GET.get('search', '')
    statut_filter = request.GET.get('statut', '')
    categorie_filter = request.GET.get('categorie', '')

    if search:
        responses = responses.filter(
            Q(lettre__subject__icontains=search) | Q(lettre__description__icontains=search)
        )
    if statut_filter:
        responses = responses.filter(statut=statut_filter)
    if categorie_filter:
        responses = responses.filter(lettre__category=categorie_filter)

    lettres_with_responses = [
        {
            'lettre': response.lettre,
            'response': response,
        }
        for response in responses
    ]

    paginator = Paginator(lettres_with_responses, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'destination': destination,
        'user_role': profile.role,
        'categories': Lettre.objects.values_list('category', flat=True).distinct(),
        'search': search,
        'statut_filter': statut_filter,
        'categorie_filter': categorie_filter,
    }
    return render(request, 'response_requet/user_dashboard.html', context)

@login_required
def new_lettres(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
        })

    if profile.role not in ['super_admin', 'admin_saisie', 'saisie_ec']:
        messages.error(request, "Vous n'êtes pas autorisé à créer des requêtes.")
        return redirect('lettres:dashboard')

    if request.method == 'POST':
        form = LettreForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                if profile.role == 'saisie_ec' and form.cleaned_data['service'] != profile.service:
                    messages.error(request, "Vous ne pouvez créer des requêtes que pour votre service.")
                    return render(request, 'new_lettres.html', {'form': form, 'user_role': profile.role})
                if profile.role == 'admin_saisie' and not (form.cleaned_data['sent_to_all_destinations'] or profile.destination in form.cleaned_data['destinations']):
                    messages.error(request, "Vous ne pouvez créer des requêtes que pour votre destination.")
                    return render(request, 'new_lettres.html', {'form': form, 'user_role': profile.role})

                lettre = form.save()
                destinations = Destination.objects.all() if lettre.sent_to_all_destinations else lettre.destinations.all()
                for destination in destinations:
                    Response.objects.get_or_create(
                        lettre=lettre,
                        destination=destination,
                        user=None,  # For admin_reponse responses
                        defaults={'statut': 'en_attente'}
                    )
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': 'Requête enregistrée avec succès.'})
                messages.success(request, "Requête enregistrée avec succès.")
                return redirect('lettres:dashboard')
            except Exception as e:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'errors': str(e)}, status=400)
                messages.error(request, f"Erreur lors de l'enregistrement : {str(e)}")
        else:
            errors = {field: [error for error in errors] for field, errors in form.errors.items()}
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': errors}, status=400)
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        initial = {'service': profile.service} if profile.role == 'saisie_ec' else {}
        if profile.role == 'admin_saisie':
            initial['destinations'] = [profile.destination]
        form = LettreForm(initial=initial)

    return render(request, 'create_requet/new_lettres.html', {'form': form, 'user_role': profile.role})

import logging
logger = logging.getLogger(__name__)
@login_required
def submit_response(request, lettre_id):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        logger.error("UserProfile does not exist for user: %s", request.user.username)
        return JsonResponse({'success': False, 'message': 'Votre compte n’a pas de profil utilisateur configuré.'})

    if profile.role not in ['admin_reponse', 'saisie_er']:
        logger.error("Unauthorized access by user: %s, role: %s", request.user.username, profile.role)
        return JsonResponse({'success': False, 'message': "Vous n'êtes pas autorisé à répondre aux requêtes."})

    destination = profile.destination
    if not destination:
        logger.error("No destination for user: %s", request.user.username)
        return JsonResponse({'success': False, 'message': 'Aucune destination associée à votre profil.'})

    lettre = get_object_or_404(Lettre, id=lettre_id)
    if profile.role == 'saisie_er' and lettre.service != profile.service:
        logger.error("Service mismatch for user: %s, lettre: %s", request.user.username, lettre.id)
        return JsonResponse({'success': False, 'message': "Vous ne pouvez répondre qu'aux requêtes de votre service."})

    if not (lettre.destinations.filter(id=destination.id).exists() or lettre.sent_to_all_destinations):
        logger.error("Unauthorized lettre access by user: %s, lettre: %s", request.user.username, lettre.id)
        return JsonResponse({'success': False, 'message': "Vous n'êtes pas autorisé à répondre à cette requête."})

    response, created = Response.objects.get_or_create(
        lettre=lettre,
        destination=destination,
        user=None if profile.role == 'admin_reponse' else request.user,
        defaults={'statut': 'en_attente'}
    )

    if request.method == 'POST':
        form = ResponseForm(request.POST, request.FILES, instance=response, lettre=lettre)
        if form.is_valid():
            response = form.save(commit=False)
            # Set statut to 'repondu' only if response_file is provided
            response_file = form.cleaned_data.get('response_file')
            if response_file:
                response.statut = 'repondu'
                response.date_reponse = datetime.now().date()
                response.temps_reponse = math.floor((datetime.now().date() - lettre.date).days * 24)
            else:
                response.statut = 'en_attente'  # Keep en_attente if no file
            response.user = None if profile.role == 'admin_reponse' else request.user
            try:
                response.save()
                logger.info("Response saved: ID=%s, File=%s", response.id, response.response_file.path if response.response_file else None)
            except Exception as e:
                logger.error("Failed to save response: %s", str(e))
                return JsonResponse({'success': False, 'message': f'Erreur lors de l\'enregistrement: {str(e)}'}, status=500)

            # Update lettre status
            expected_response_count = Destination.objects.count() if lettre.sent_to_all_destinations else lettre.destinations.count()
            responded_count = lettre.reponses.filter(statut='repondu').count()
            logger.debug("Lettre: %s, Expected: %d, Responded: %d", lettre.id, expected_response_count, responded_count)
            if responded_count >= expected_response_count:
                lettre.statut = 'repondu'
            elif lettre.is_overdue:
                lettre.statut = 'en_retard'
            else:
                lettre.statut = 'en_attente'
            try:
                lettre.save()
                logger.info("Lettre status updated: %s, new status: %s", lettre.id, lettre.statut)
            except Exception as e:
                logger.error("Failed to save lettre: %s", str(e))
                return JsonResponse({'success': False, 'message': f'Erreur lors de la mise à jour de la lettre: {str(e)}'}, status=500)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Réponse enregistrée avec succès.',
                    'redirect_url': 'dashboard_Reponse/'
                })
            messages.success(request, 'Réponse enregistrée avec succès.')
            return redirect('lettres:dashboard_Reponse')
        else:
            logger.error("Form errors: %s", form.errors.as_json())
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': 'Erreur dans le formulaire.',
                    'errors': form.errors.as_json()
                }, status=400)
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = ResponseForm(instance=response, lettre=lettre)

    return render(request, 'response_requet/response_form.html', {
        'form': form,
        'lettre': lettre,
        'destination': destination,
        'user_role': profile.role
    })

@login_required
def response_detail(request, response_id):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        logger.error("UserProfile does not exist for user: %s", request.user.username)
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
        })

    if profile.role not in ['admin_reponse', 'saisie_er']:
        logger.error("Unauthorized access to response detail by user: %s, role: %s", request.user.username, profile.role)
        messages.error(request, "Vous n'êtes pas autorisé à voir les détails de cette réponse.")
        return redirect('lettres:dashboard_Reponse')

    response = get_object_or_404(Response, id=response_id, destination=profile.destination)
    if profile.role == 'saisie_er' and response.lettre.service != profile.service:
        logger.error("Service mismatch for user: %s, response: %s", request.user.username, response.id)
        messages.error(request, "Vous ne pouvez voir que les réponses de votre service.")
        return redirect('lettres:dashboard_Reponse')

    context = {
        'response': response,
        'lettre': response.lettre,
        'destination': profile.destination,
        'user_role': profile.role,
    }
    return render(request, 'response_requet/response_detail.html', context)

    

@login_required
def destinations(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
        })

    if profile.role != 'super_admin':
        messages.error(request, "Vous n'êtes pas autorisé à gérer les destinations.")
        return redirect('lettres:dashboard')

    destinations = Destination.objects.all()

    if request.method == 'POST':
        form = DestinationForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Destination ajoutée avec succès.')
                return redirect('lettres:destinations')
            except IntegrityError:
                messages.error(request, "Erreur : Cette destination existe déjà.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    context = {
        'destinations': destinations,
        'form': DestinationForm(),
        'user_role': profile.role,
    }
    return render(request, 'menu/destinations.html', context)

@login_required
def statistics(request):
    """
    View: Display statistics of requests per region/destination
    based on the authenticated user's role and permissions.
    """

    # --- 1. Retrieve the user profile ---
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return render(request, 'error.html', {
            'error': (
                "Votre compte n’a pas de profil utilisateur configuré. "
                "Contactez l’administrateur."
            )
        })

    # --- 2. Base queryset for letters (lettres) ---
    lettres_qs = Lettre.objects.all()

    if profile.role == 'saisie_ec':
        lettres_qs = lettres_qs.filter(service=profile.service)

    elif profile.role in ['admin_reponse', 'saisie_er']:
        lettres_qs = lettres_qs.filter(
            Q(destinations=profile.destination) |
            Q(sent_to_all_destinations=True)
        )
        if profile.role == 'saisie_er':
            lettres_qs = lettres_qs.filter(service=profile.service)

    elif profile.role == 'admin_saisie':
        lettres_qs = lettres_qs.filter(
            Q(destinations=profile.destination) |
            Q(sent_to_all_destinations=True)
        )

    # --- 3. Determine destinations to include ---
    if profile.role in ['admin_reponse', 'saisie_er', 'admin_saisie']:
        destinations = [profile.destination] if profile.destination else []
    else:
        destinations = Destination.objects.all()

    # --- 4. Prepare statistics for each destination ---
    region_stats = []
    for dest in destinations:
        responses_qs = Response.objects.filter(destination=dest)

        # Apply additional filters based on role
        if profile.role == 'saisie_ec':
            responses_qs = responses_qs.filter(lettre__service=profile.service)
        elif profile.role in ['admin_reponse', 'saisie_er', 'admin_saisie']:
            responses_qs = responses_qs.filter(destination=profile.destination)
            if profile.role == 'saisie_er':
                responses_qs = responses_qs.filter(lettre__service=profile.service)

        # Counts
        total_requetes = responses_qs.count()
        en_attente = responses_qs.filter(statut='en_attente').count()
        repondues = responses_qs.filter(statut='repondu').count()
        en_retard = responses_qs.filter(statut='en_retard').count()

        # Rates and averages
        taux_reponse = (repondues / total_requetes * 100) if total_requetes else 0
        avg_time = (
            responses_qs.filter(statut='repondu')
            .aggregate(avg=Avg('temps_reponse'))['avg'] or 0
        )

        # Append statistics
        region_stats.append({
            'destination': getattr(dest, 'nom', 'N/A'),
            'total': total_requetes,
            'en_attente': en_attente,
            'repondues': repondues,
            'en_retard': en_retard,
            'taux_reponse': round(taux_reponse, 1),
            'avg_response_time': round(avg_time, 1),
        })

    # --- 5. Render template ---
    return render(request, 'menu/statistics.html', {
        'region_stats': region_stats,
        'user_role': profile.role,
    })
@login_required
def archive(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
        })

    # Define cutoff dates
    one_year_ago = datetime.now().date() - timedelta(days=365)  # 1 year ago for "en cours"
    one_month_ago = datetime.now().date() - timedelta(days=30)  # 1 month ago for "repondu"

    # Base query for archived letters
    lettres = Lettre.objects.filter(
        Q(statut__in=['en_attente', 'en_retard'], deadline__lte=one_year_ago) |  # En cours, deadline > 1 year
        Q(statut='repondu', reponses__date_reponse__lte=one_month_ago)  # Repondu, response date > 1 month
    ).distinct()

    # Apply role-based filtering
    if profile.role == 'saisie_ec':
        lettres = lettres.filter(service=profile.service)
    elif profile.role in ['admin_reponse', 'saisie_er']:
        lettres = lettres.filter(Q(destinations=profile.destination) | Q(sent_to_all_destinations=True))
        if profile.role == 'saisie_er':
            lettres = lettres.filter(service=profile.service)
    elif profile.role == 'admin_saisie':
        lettres = lettres.filter(Q(destinations=profile.destination) | Q(sent_to_all_destinations=True))

    # Prepare lettres with additional data
    lettres_with_data = []
    for lettre in lettres:
        # Get the latest response with statut='repondu'
        last_response = lettre.reponses.filter(statut='repondu').order_by('-date_reponse').first()
        lettres_with_data.append({
            'lettre': lettre,
            'last_response_date': last_response.date_reponse if last_response else None
        })

    # Paginate lettres
    paginator = Paginator(lettres_with_data, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'user_role': profile.role,
    }
    return render(request, 'menu/archive.html', context)

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('lettres:dashboard')
            else:
                messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
        else:
            messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
    else:
        form = LoginForm()
    return render(request, 'login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('lettres:login')


@login_required
def destination_interface(request, destination_name):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
        })

    if profile.role not in ['admin_reponse', 'saisie_er'] or profile.destination.nom != destination_name:
        messages.error(request, "Vous n'êtes pas autorisé à accéder à cette interface.")
        return redirect('lettres:dashboard')

    destination = get_object_or_404(Destination, nom=destination_name)
    lettres = Lettre.objects.filter(Q(destinations=destination) | Q(sent_to_all_destinations=True))
    if profile.role == 'saisie_er':
        lettres = lettres.filter(service=profile.service)

    if request.method == 'POST':
        lettre_id = request.POST.get('lettre_id')
        lettre = get_object_or_404(Lettre, pk=lettre_id)
        if profile.role == 'saisie_er' and lettre.service != profile.service:
            messages.error(request, "Vous ne pouvez répondre qu'aux requêtes de votre service.")
            return redirect('lettres:destination_interface', destination_name=destination_name)

        form = ResponseForm(request.POST, request.FILES)
        if form.is_valid():
            response = form.save(commit=False)
            response.lettre = lettre
            response.destination = destination
            response.statut = 'repondu'
            response.date_reponse = datetime.now().date()

            reception_date = lettre.date
            response_time = (datetime.now().date() - reception_date).total_seconds() / 3600
            response.temps_reponse = math.floor(response_time)

            response.save()

            expected_response_count = Destination.objects.count() if lettre.sent_to_all_destinations else lettre.destinations.count()
            if lettre.reponses.filter(statut='repondu').count() == expected_response_count:
                lettre.statut = 'repondu'
                lettre.save()

            messages.success(request, 'Réponse enregistrée avec succès.')
            return redirect('lettres:destination_interface', destination_name=destination_name)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    context = {
        'destination': destination,
        'lettres': lettres,
        'form': ResponseForm(),
        'user_role': profile.role,
    }
    return render(request, 'destination_interface.html', context)

@login_required
@require_POST
def send_email_reminder(request, pk):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return JsonResponse({'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    if profile.role not in ['super_admin', 'admin_saisie', 'saisie_ec']:
        return JsonResponse({'message': "Vous n'êtes pas autorisé à envoyer des rappels."}, status=403)

    lettre = get_object_or_404(Lettre, pk=pk)
    if profile.role == 'saisie_ec' and lettre.service != profile.service:
        return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre service."}, status=403)

    destination_name = request.POST.get('destination')
    destination = get_object_or_404(Destination, nom=destination_name)
    response = Response.objects.filter(lettre=lettre, destination=destination).first()

    if not response:
        response = Response.objects.create(lettre=lettre, destination=destination, statut='en_attente')

    if not destination.email:
        return JsonResponse({'message': f"Erreur: Aucun email configuré pour {destination_name}"}, status=400)

    try:
        send_mail(
            subject=f"Rappel: {lettre.subject}",
            message=f"Rappel pour la requête: {lettre.subject}. Veuillez répondre avant {lettre.deadline}.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[destination.email],
            fail_silently=False,
        )
        rappel = Rappel.objects.create(
            response=response,
            type='email',
            date=datetime.now().date(),
            time=datetime.now().time(),
            message=f"Rappel pour {lettre.subject}",
            status='sent'
        )
        response.rappels.add(rappel)
        lettre.rappels_envoyes += 1
        lettre.date_dernier_rappel = datetime.now().date()
        lettre.save()
        response.save()
        return JsonResponse({'message': 'Email envoyé avec succès'})
    except Exception as e:
        rappel = Rappel.objects.create(
            response=response,
            type='email',
            date=datetime.now().date(),
            time=datetime.now().time(),
            message=f"Rappel pour {lettre.subject}",
            status='failed'
        )
        response.rappels.add(rappel)
        return JsonResponse({'message': f"Erreur lors de l'envoi de l'email: {str(e)}"}, status=500)

@login_required
@require_POST
def send_automatic_reminders(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return JsonResponse({'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    if profile.role not in ['super_admin', 'admin_saisie', 'saisie_ec']:
        return JsonResponse({'message': "Vous n'êtes pas autorisé à envoyer des rappels automatiques."}, status=403)

    settings = SystemSettings.objects.get(user=request.user)
    if not settings.email_notifications:
        return JsonResponse({'message': 'Les notifications par email sont désactivées.'}, status=400)

    lettres = Lettre.objects.filter(statut='en_attente')
    if profile.role == 'saisie_ec':
        lettres = lettres.filter(service=profile.service)
    elif profile.role == 'admin_saisie':
        lettres = lettres.filter(Q(destinations=profile.destination) | Q(sent_to_all_destinations=True))

    reminder_count = 0
    errors = []

    for lettre in lettres:
        last_reminder = lettre.date_dernier_rappel
        now = datetime.now().date()
        if last_reminder and (now - last_reminder).days < settings.reminder_frequency / 24:
            continue

        destinations = Destination.objects.all() if lettre.sent_to_all_destinations else lettre.destinations.all()
        for destination in destinations:
            response = Response.objects.filter(lettre=lettre, destination=destination).first()
            if not response:
                response = Response.objects.create(lettre=lettre, destination=destination, statut='en_attente')

            if response.statut != 'en_attente':
                continue

            if not destination.email:
                errors.append(f"Aucun email pour {destination.nom}")
                continue

            try:
                send_mail(
                    subject=f"Rappel Automatique: {lettre.subject}",
                    message=f"Rappel automatique pour la requête: {lettre.subject}. Veuillez répondre avant {lettre.deadline}.",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[destination.email],
                    fail_silently=False,
                )
                rappel = Rappel.objects.create(
                    response=response,
                    type='email',
                    date=now,
                    time=datetime.now().time(),
                    message=f"Rappel automatique pour {lettre.subject}",
                    status='sent'
                )
                response.rappels.add(rappel)
                lettre.rappels_envoyes += 1
                lettre.date_dernier_rappel = now
                lettre.save()
                response.save()
                reminder_count += 1
            except Exception as e:
                rappel = Rappel.objects.create(
                    response=response,
                    type='email',
                    date=now,
                    time=datetime.now().time(),
                    message=f"Rappel automatique pour {lettre.subject}",
                    status='failed'
                )
                response.rappels.add(rappel)
                errors.append(f"Erreur pour {destination.nom}: {str(e)}")

    if errors:
        return JsonResponse({'message': f"{reminder_count} rappels envoyés. Erreurs: {', '.join(errors)}"}, status=200 if reminder_count > 0 else 500)
    return JsonResponse({'message': f"{reminder_count} rappels envoyés avec succès."})

@login_required
@require_POST
def send_global_reminder(request, pk):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return JsonResponse({'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    if profile.role not in ['super_admin', 'admin_saisie', 'saisie_ec']:
        return JsonResponse({'message': "Vous n'êtes pas autorisé à envoyer des rappels globaux."}, status=403)

    lettre = get_object_or_404(Lettre, pk=pk)
    if profile.role == 'saisie_ec' and lettre.service != profile.service:
        return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre service."}, status=403)
    if profile.role == 'admin_saisie' and not (lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations):
        return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre destination."}, status=403)

    destinations = Destination.objects.all() if lettre.sent_to_all_destinations else lettre.destinations.all()
    reminder_count = 0
    errors = []

    for destination in destinations:
        response = Response.objects.filter(lettre=lettre, destination=destination).first()
        if not response:
            response = Response.objects.create(lettre=lettre, destination=destination, statut='en_attente')

        if response.statut != 'en_attente':
            continue

        if not destination.email:
            errors.append(f"Aucun email pour {destination.nom}")
            continue

        try:
            send_mail(
                subject=f"Rappel Global: {lettre.subject}",
                message=f"Rappel global pour la requête: {lettre.subject}. Veuillez répondre avant {lettre.deadline}.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[destination.email],
                fail_silently=False,
            )
            rappel = Rappel.objects.create(
                response=response,
                type='email',
                date=datetime.now().date(),
                time=datetime.now().time(),
                message=f"Rappel global pour {lettre.subject}",
                status='sent'
            )
            response.rappels.add(rappel)
            reminder_count += 1
        except Exception as e:
            rappel = Rappel.objects.create(
                response=response,
                type='email',
                date=datetime.now().date(),
                time=datetime.now().time(),
                message=f"Rappel global pour {lettre.subject}",
                status='failed'
            )
            response.rappels.add(rappel)
            errors.append(f"Erreur pour {destination.nom}: {str(e)}")

    lettre.rappels_envoyes += reminder_count
    lettre.date_dernier_rappel = datetime.now().date()
    lettre.save()

    if errors:
        return JsonResponse({'message': f"{reminder_count} rappels envoyés. Erreurs: {', '.join(errors)}"}, status=200 if reminder_count > 0 else 500)
    return JsonResponse({'message': f"{reminder_count} rappels globaux envoyés avec succès."})

@login_required
def lettre_detail(request, pk):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return JsonResponse({'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    lettre = get_object_or_404(Lettre, pk=pk)
    if profile.role == 'saisie_ec' and lettre.service != profile.service:
        return JsonResponse({'message': "Vous n'êtes pas autorisé à voir les détails de cette requête."}, status=403)
    if profile.role in ['admin_reponse', 'saisie_er'] and not (lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations):
        return JsonResponse({'message': "Vous n'êtes pas autorisé à voir les détails de cette requête."}, status=403)
    if profile.role == 'saisie_er' and lettre.service != profile.service:
        return JsonResponse({'message': "Vous ne pouvez voir que les requêtes de votre service."}, status=403)
    if profile.role == 'admin_saisie' and not (lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations):
        return JsonResponse({'message': "Vous n'êtes pas autorisé à voir les détails de cette requête."}, status=403)

    destinations_data = []
    if lettre.sent_to_all_destinations:
        destinations = Destination.objects.all()
    else:
        destinations = lettre.destinations.all()

    for destination in destinations:
        response, created = Response.objects.get_or_create(
            lettre=lettre,
            destination=destination,
            defaults={'statut': 'en_attente'}
        )
        rappels = list(response.rappels.values('type', 'date', 'time', 'message', 'status'))
        destinations_data.append({
            'nom': destination.nom,
            'statut': response.statut,
            'date_reponse': response.date_reponse.strftime('%d/%m/%Y') if response.date_reponse else None,
            'rappels': rappels,
            'email': destination.email or ''
        })

    today = datetime.now().date()
    days_overdue = (today - lettre.deadline).days if lettre.deadline and today > lettre.deadline else 0
    days_until_deadline = (lettre.deadline - today).days if lettre.deadline and today <= lettre.deadline else 0

    data = {
        'subject': lettre.subject,
        'category': lettre.category,
        'date': lettre.date.strftime('%d/%m/%Y') if lettre.date else None,
        'deadline': lettre.deadline.strftime('%d/%m/%Y') if lettre.deadline else None,
        'priority': lettre.priority,
        'get_priority_display': lettre.get_priority_display(),
        'statut': lettre.statut,
        'get_statut_display': lettre.get_statut_display(),
        'service': lettre.service or '',
        'destinations': destinations_data,
        'sent_to_all_destinations': lettre.sent_to_all_destinations,
        'days_overdue': days_overdue,
        'days_until_deadline': days_until_deadline,
        'rappels_envoyes': lettre.rappels_envoyes or 0,
        'response_template': lettre.response_template.url if lettre.response_template else None,
    }

    return JsonResponse(data)

@login_required
@require_GET
def get_rappels(request, pk, destination_name):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return JsonResponse({'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    lettre = get_object_or_404(Lettre, pk=pk)
    if profile.role == 'saisie_ec' and lettre.service != profile.service:
        return JsonResponse({'message': "Vous n'êtes pas autorisé à voir les rappels de cette requête."}, status=403)
    if profile.role in ['admin_reponse', 'saisie_er'] and not (lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations):
        return JsonResponse({'message': "Vous n'êtes pas autorisé à voir les rappels de cette requête."}, status=403)
    if profile.role == 'saisie_er' and lettre.service != profile.service:
        return JsonResponse({'message': "Vous ne pouvez voir que les rappels de votre service."}, status=403)
    if profile.role == 'admin_saisie' and not (lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations):
        return JsonResponse({'message': "Vous n'êtes pas autorisé à voir les rappels de cette requête."}, status=403)

    destination = get_object_or_404(Destination, nom=destination_name)
    response = Response.objects.filter(lettre=lettre, destination=destination).first()

    if not response:
        response = Response.objects.create(lettre=lettre, destination=destination, statut='en_attente')

    rappels = list(response.rappels.values('type', 'date', 'time', 'message', 'status'))

    data = {'rappels': rappels, 'email': destination.email or 'N/A'}
    return JsonResponse(data)

@login_required
def settings_page(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Votre compte n'a pas de profil utilisateur configuré. Veuillez contacter l'administrateur.")
        return render(request, 'error.html', {
            'error': "Votre compte n'a pas de profil utilisateur configuré. Veuillez contacter l'administrateur."
        })

    if profile.role != 'super_admin':
        messages.error(request, "Vous n'avez pas les autorisations nécessaires pour accéder aux paramètres.")
        return redirect('lettres:dashboard')

    settings, created = SystemSettings.objects.get_or_create(user=request.user)
    form = SystemSettingsForm(instance=settings)
    user_form = UserCreationForm()
    destination_form = DestinationForm()
    users = UserProfile.objects.all()  # Include all users, including super_admin
    destinations = Destination.objects.all()

    if request.method == 'POST':
        if 'save_settings' in request.POST:
            form = SystemSettingsForm(request.POST, instance=settings)
            if form.is_valid():
                form.save()
                messages.success(request, "Les paramètres ont été enregistrés avec succès.")
                return redirect('lettres:settings?tab=notifications')
            else:
                messages.error(request, "Erreur lors de l'enregistrement des paramètres. Veuillez vérifier les informations saisies.")

        elif 'add_user' in request.POST:
            user_form = UserCreationForm(request.POST)
            if user_form.is_valid():
                try:
                    user = user_form.save()
                    messages.success(request, f"L'utilisateur '{user.username}' a été ajouté avec succès.")
                    return redirect('lettres:settings?tab=users')
                except Exception:
                    messages.error(request, "Une erreur est survenue lors de la création de l'utilisateur. Veuillez réessayer.")
            else:
                messages.error(request, "Erreur lors de la création de l'utilisateur. Veuillez vérifier les informations saisies.")

        elif 'delete_user' in request.POST:
            user_id = request.POST.get('user_id')
            try:
                user_profile = UserProfile.objects.get(user__id=user_id)
                if user_profile.role == 'super_admin':
                    messages.error(request, "Le Super Administrateur ne peut pas être supprimé.")
                else:
                    user = user_profile.user
                    user_profile.delete()
                    user.delete()
                    messages.success(request, "L'utilisateur a été supprimé avec succès.")
                return redirect('lettres:settings?tab=users')
            except UserProfile.DoesNotExist:
                messages.error(request, "L'utilisateur sélectionné n'existe pas.")
                return redirect('lettres:settings?tab=users')

        elif 'add_destination' in request.POST:
            destination_form = DestinationForm(request.POST)
            if destination_form.is_valid():
                try:
                    destination_form.save()
                    messages.success(request, "La destination a été ajoutée avec succès.")
                    return redirect('lettres:settings?tab=destinations')
                except Exception:
                    messages.error(request, "Une erreur est survenue lors de l'ajout de la destination. Veuillez réessayer.")
            else:
                messages.error(request, "Erreur lors de l'ajout de la destination. Veuillez vérifier les informations saisies.")

        elif 'edit_destination' in request.POST:
            destination_id = request.POST.get('destination_id')
            try:
                destination = Destination.objects.get(id=destination_id)
                destination_form = DestinationForm(request.POST, instance=destination)
                if destination_form.is_valid():
                    destination_form.save()
                    messages.success(request, "La destination a été modifiée avec succès.")
                    return redirect('lettres:settings?tab=destinations')
                else:
                    messages.error(request, "Erreur lors de la modification de la destination. Veuillez vérifier les informations saisies.")
            except Destination.DoesNotExist:
                messages.error(request, "La destination sélectionnée n'existe pas.")
                return redirect('lettres:settings?tab=destinations')

        elif 'delete_destination' in request.POST:
            destination_id = request.POST.get('destination_id')
            try:
                destination = Destination.objects.get(id=destination_id)
                destination.delete()
                messages.success(request, "La destination a été supprimée avec succès.")
                return redirect('lettres:settings?tab=destinations')
            except Destination.DoesNotExist:
                messages.error(request, "La destination sélectionnée n'existe pas.")
                return redirect('lettres:settings?tab=destinations')

    context = {
        'form': form,
        'user_form': user_form,
        'destination_form': destination_form,
        'users': users,
        'destinations': destinations,
        'user_role': profile.role,
        'active_tab': request.GET.get('tab', 'notifications'),
    }
    return render(request, 'menu/settings.html', context)
