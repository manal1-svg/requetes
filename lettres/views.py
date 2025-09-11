
import json
import logging
from time import timezone
from django.middleware.csrf import logger
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from functools import cache
from django.db.models import Avg, Count, Q, Case, When, IntegerField
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.db import IntegrityError
from .models import Lettre, Destination, Response, SystemSettings, UserProfile, Rappel 
from .forms import LoginForm, LettreForm, ResponseApprovalForm, ResponseForm, SystemSettingsForm, UserCreationForm, DestinationForm, UserProfileForm
from datetime import date, datetime, timedelta

import math
from django.db import IntegrityError
from django.core.exceptions import ValidationError 
from django.urls import reverse
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.middleware.csrf import get_token
from django.contrib import messages
from django.conf import settings



from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail
from django.conf import settings
from .models import Lettre, Destination, Response, Rappel
from datetime import datetime
from django.views.decorators.csrf import csrf_exempt

from celery import shared_task  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

@login_required
def profile(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        # Create a default Destination if none exist
        if not Destination.objects.exists():
            default_destination = Destination.objects.create(nom='Oujda-Angad', email='default@example.com')
            logger.info(f"Created default destination: Oujda-Angad")
        else:
            default_destination = Destination.objects.first()

        # Determine default role and service
        default_role = 'super_admin' if request.user.is_superuser else 'saisie_ec'
        default_service = None if default_role in ['super_admin', 'admin_saisie', 'admin_reponse'] else 'SGP'

        profile = UserProfile.objects.create(
            user=request.user,
            role=default_role,
            destination=default_destination if default_role in ['saisie_ec', 'saisie_er', 'admin_reponse', 'admin_saisie'] else None,
            service=default_service
        )
        logger.info(f"Created default profile for user {request.user.username} with role {profile.role}, destination {profile.destination}, service {profile.service}")
        messages.info(request, "Un profil par défaut a été créé. Veuillez le mettre à jour si nécessaire.")

    context = {
        'user_role': profile.role,
        'user_profile': profile  # Added for template access
    }
    return render(request, 'menu/profile.html', context)

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
            logger.info(f"Created super_admin profile for user {request.user.username}")
        else:
            logger.error(f"User {request.user.username} has no UserProfile configured")
            return render(request, 'error.html', {
                'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
            }, status=403)

    # Redirect admin_reponse and saisie_er to their specific dashboard
    if profile.role in ['admin_reponse', 'saisie_er']:
        return redirect('lettres:dashboard_Reponse')

    # Filter lettres based on role
    if profile.role == 'super_admin':
        lettres = Lettre.objects.all()  # Super admins see all letters
    else:
        # Filter by destination (either directly assigned or sent to all)
        lettres = Lettre.objects.filter(
            Q(destinations=profile.destination) | Q(sent_to_all_destinations=True)
        ).distinct()
        # For saisie_ec, further filter by service
        if profile.role == 'saisie_ec':
            lettres = lettres.filter(service=profile.service)

    # Update status for each lettre (for super_admin only)
    if profile.role == 'super_admin':
        for lettre in lettres:
            lettre.update_status()

    # Apply additional filters
    search = request.GET.get('search', '')
    statut_filter = request.GET.get('statut', '')
    categorie_filter = request.GET.get('category', '')
    destination_filter = request.GET.get('destination', '')

    if search:
        lettres = lettres.filter(Q(subject__icontains=search) | Q(category__icontains=search))
    if statut_filter:
        if statut_filter == 'revision_requested':
            # Filter letters where the user's destination has a response with approval_status='revision_requested'
            lettres = lettres.filter(
                reponses__destination=profile.destination,
                reponses__approval_status='revision_requested'
            ).distinct()
        else:
            lettres = lettres.filter(statut=statut_filter)
    if categorie_filter:
        lettres = lettres.filter(category=categorie_filter)
    if destination_filter:
        lettres = lettres.filter(
            Q(destinations__id=destination_filter) | Q(sent_to_all_destinations=True)
        ).distinct()

    # Calculate stats for cards
    lettres_en_attente = lettres.filter(statut='en_attente')
    lettres_repondues = lettres.filter(statut='repondu')
    lettres_en_retard = lettres.filter(statut='en_retard')

    # Calculate "En Cours" for saisie_ec and admin_saisie (letters awaiting response for their destination)
    lettres_en_cours = 0
    if profile.role in ['saisie_ec', 'admin_saisie']:
        lettres_en_cours = sum(
            1 for lettre in lettres
            if Response.objects.filter(
                lettre=lettre,
                destination=profile.destination,
                statut__in=['en_attente', 'en_retard']
            ).exists()
        )

    # Calculate average response time
    avg_response_time = 0
    responded_lettres = lettres_repondues
    if responded_lettres.exists():
        total_hours = sum(
            (lettre.reponses.filter(destination=profile.destination).first().temps_reponse
             for lettre in responded_lettres
             if lettre.reponses.filter(destination=profile.destination).exists() and
                lettre.reponses.filter(destination=profile.destination).first().temps_reponse is not None),
            0
        )
        responded_count = sum(
            1 for lettre in responded_lettres
            if lettre.reponses.filter(destination=profile.destination).exists()
        )
        avg_response_time = total_hours / responded_count if responded_count > 0 else 0

    today = date.today()
    lettres_with_progress = []
    for lettre in lettres:
        # Count responses for all destinations
        responded_count = lettre.reponses.filter(statut='repondu').count()
        total_destinations = (
            lettre.destinations.count() if not lettre.sent_to_all_destinations
            else Destination.objects.count()
        )
        days_overdue = (
            (today - lettre.deadline).days if lettre.deadline and today > lettre.deadline
            else 0
        )
        days_until_deadline = (
            (lettre.deadline - today).days if lettre.deadline and today <= lettre.deadline
            else 0
        )
        # Get the response status for the user's specific destination
        user_destination_status = None
        user_response_file_url = None
        if profile.role != 'super_admin':
            if lettre.sent_to_all_destinations or lettre.destinations.filter(id=profile.destination.id).exists():
                response, created = Response.objects.get_or_create(
                    lettre=lettre,
                    destination=profile.destination,
                    defaults={'statut': 'en_attente', 'user': request.user if profile.role == 'saisie_ec' else None}
                )
                # Check approval_status first for revision_requested
                user_destination_status = response.approval_status if response.approval_status == 'revision_requested' else response.statut
                if response.response_file:
                    try:
                        user_response_file_url = response.response_file.url
                    except Exception as e:
                        logger.error(f"Error accessing response_file URL for lettre {lettre.id}, destination {profile.destination.nom}: {str(e)}")
                        user_response_file_url = None
                if created:
                    logger.info(f"Created new Response for lettre {lettre.id}, destination {profile.destination.nom} with status {response.statut}")
            else:
                user_destination_status = 'en_attente'
                logger.warning(f"No access to lettre {lettre.id} for destination {profile.destination.nom}")

        lettres_with_progress.append({
            'lettre': lettre,
            'service': lettre.service,
            'responded_count': responded_count,
            'total_destinations': total_destinations,
            'days_overdue': days_overdue,
            'days_until_deadline': days_until_deadline,
            'user_destination_status': user_destination_status,
            'user_response_file_url': user_response_file_url,
            'created_by': lettre.created_by.username if lettre.created_by else 'Unknown'
        })

    total_lettres = lettres.count()

    # Paginate lettres
    paginator = Paginator(lettres_with_progress, 8)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    form = LettreForm(user_profile=profile) if profile.role in ['super_admin', 'admin_saisie', 'saisie_ec'] else None

    context = {
        'form': form,
        'lettres': page_obj.object_list,
        'page_obj': page_obj,
        'lettres_en_attente': lettres_en_attente,
        'lettres_repondues': lettres_repondues,
        'lettres_en_retard': lettres_en_retard,
        'lettres_en_cours': lettres_en_cours,
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
def new_lettres(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        logger.error(f"User {request.user.username} has no UserProfile configured")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'}, status=400)
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
        }, status=403)

    # Validate profile for saisie_ec/saisie_er
    if profile.role in ['saisie_ec', 'saisie_er']:
        if not profile.service:
            logger.error(f"User {request.user.username} with role {profile.role} has no service configured")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': 'Votre compte n’a pas de service configuré. Contactez l’administrateur.'}, status=400)
            return render(request, 'error.html', {
                'error': 'Votre compte n’a pas de service configuré. Contactez l’administrateur.'
            }, status=403)
        valid_services = dict(Lettre.SERVICE_CHOICES)
        if profile.service not in valid_services:
            logger.error(f"Invalid service {profile.service} for user {request.user.username} with role {profile.role}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f"Le service '{profile.service}' n'est pas valide. Contactez l’administrateur."}, status=400)
            return render(request, 'error.html', {
                'error': f"Le service '{profile.service}' n'est pas valide. Contactez l’administrateur."
            }, status=403)

    if profile.role not in ['super_admin', 'admin_saisie', 'saisie_ec', 'directeur_regional']:
        logger.warning(f"User {request.user.username} with role {profile.role} attempted to access new_lettres")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': "Vous n'êtes pas autorisé à créer des requêtes."}, status=403)
        messages.error(request, "Vous n'êtes pas autorisé à créer des requêtes.")
        return redirect('lettres:dashboard')

    submission_id = request.headers.get('X-Submission-ID')
    if request.method == 'POST' and submission_id:
        cache_key = f'submission_{submission_id}'
        if cache.get(cache_key):
            logger.warning(f"Duplicate submission detected: {submission_id}")
            return JsonResponse({'success': False, 'errors': 'Duplicate submission detected.'}, status=400)
        cache.set(cache_key, True, timeout=30)

    if not profile.destination and profile.role != 'super_admin':
        if Destination.objects.exists():
            profile.destination = Destination.objects.first()
            logger.info(f"Set default destination to {profile.destination.nom} for user {request.user.username}")
            profile.save()
        else:
            profile.destination = Destination.objects.create(nom='Oujda-Angad', email='default@example.com')
            logger.info(f"Created and set default destination Oujda-Angad for user {request.user.username}")
            profile.save()

    if request.method == 'POST':
        logger.debug(f"POST data for user {request.user.username}: {dict(request.POST)}, service={request.POST.get('service')}")
        try:
            form = LettreForm(request.POST, request.FILES, user_profile=profile)
            if form.is_valid():
                try:
                    lettre = form.save(commit=False)
                    logger.debug(f"Saving lettre with service={lettre.service} for user {request.user.username}")
                    lettre.created_by = request.user
                    lettre.save()
                    form.save_m2m()
                    destinations = Destination.objects.all() if lettre.sent_to_all_destinations else lettre.destinations.all()
                    for destination in destinations:
                        Response.objects.get_or_create(
                            lettre=lettre,
                            destination=destination,
                            user=None,
                            defaults={'statut': 'en_attente'}
                        )
                    logger.info(f"User {request.user.username} created lettre {lettre.id} with service {lettre.service} successfully")
                    if submission_id:
                        cache.delete(cache_key)
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': True, 'message': 'Requête créée avec succès.'})
                    messages.success(request, "Requête créée avec succès.")
                    return redirect('lettres:dashboard')
                except Exception as e:
                    logger.exception(f"Error saving lettre for user {request.user.username}: {str(e)}")
                    if submission_id:
                        cache.delete(cache_key)
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'errors': f"Erreur lors de l'enregistrement: {str(e)}"}, status=400)
                    messages.error(request, f"Erreur lors de l'enregistrement: {str(e)}")
            else:
                errors = {field: errors for field, errors in form.errors.items()}
                logger.error(f"Form validation failed for user {request.user.username}: {errors}")
                if submission_id:
                    cache.delete(cache_key)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'errors': errors}, status=400)
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f"{field}: {error}")
        except ValidationError as e:
            logger.error(f"Form initialization or validation failed for user {request.user.username}: {str(e)}")
            if submission_id:
                cache.delete(cache_key)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f"Erreur de validation: {str(e)}"}, status=400)
            messages.error(request, f"Erreur de validation: {str(e)}")
    else:
        try:
            initial = {
                'destinations': [profile.destination.id] if profile.destination and profile.role in ['admin_saisie', 'saisie_ec', 'directeur_regional'] else [],
                'service': profile.service if profile.role in ['saisie_ec', 'saisie_er'] else None,
                'created_by': request.user,
            }
            logger.debug(f"Initializing form with initial data: {initial} for user {request.user.username}")
            form = LettreForm(initial=initial, user_profile=profile)
        except ValidationError as e:
            logger.error(f"Form initialization failed for user {request.user.username}: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': f"Erreur d'initialisation: {str(e)}"}, status=400)
            return render(request, 'error.html', {
                'error': str(e)
            }, status=400)

    return render(request, 'create_requet/new_lettres.html', {
        'form': form,
        'user_role': profile.role,
        'user_profile': profile
    })







@login_required
def lettre_detail(request, pk):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        logger.error("UserProfile does not exist for user: %s", request.user.username)
        return JsonResponse({'success': False, 'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    # Fetch the lettre
    lettre = get_object_or_404(Lettre, pk=pk)

    # Authorization checks based on role
    authorized = False
    if profile.role == 'super_admin':
        authorized = True
    elif profile.role in ['saisie_er', 'saisie_ec']:
        authorized = lettre.service == profile.service and (
            lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations
        )
    elif profile.role in ['admin_saisie', 'admin_reponse', 'directeur_regional']:
        authorized = lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations
    else:
        logger.error("Unknown role %s for user %s", profile.role, request.user.username)
        return JsonResponse({'success': False, 'message': 'Rôle utilisateur non reconnu.'}, status=403)

    if not authorized:
        logger.error("Unauthorized access to lettre %s by user %s (role: %s)", pk, request.user.username, profile.role)
        return JsonResponse({'success': False, 'message': "Vous n'êtes pas autorisé à voir les détails de cette requête."}, status=403)

    # Filter destinations based on role
    if profile.role == 'super_admin':
        destinations = Destination.objects.all() if lettre.sent_to_all_destinations else lettre.destinations.all()
    else:
        # Restrict to user's destination only
        destinations = [profile.destination] if (
            lettre.sent_to_all_destinations or lettre.destinations.filter(id=profile.destination.id).exists()
        ) else []

    # Additional service filter for saisie_er and saisie_ec
    if profile.role in ['saisie_er', 'saisie_ec'] and destinations:
        if lettre.service != profile.service:
            destinations = []

    if not destinations:
        logger.warning("No authorized destinations found for lettre %s for user %s (role: %s)", pk, request.user.username, profile.role)
        return JsonResponse({'success': True, 'destinations': []}, status=200)

    # Prepare destinations data and count sent reminders
    destinations_data = []
    total_rappels_envoyes = 0
    for destination in destinations:
        try:
            response, created = Response.objects.get_or_create(
                lettre=lettre,
                destination=destination,
                defaults={'statut': 'en_attente'}
            )
            rappels = response.rappels.filter(status='sent').values('type', 'date', 'time', 'message', 'status')
            total_rappels_envoyes += rappels.count()
            response_file_url = response.response_file.url if response.response_file else None

            destinations_data.append({
                'nom': destination.nom,
                'statut': response.statut,
                'date_reponse': response.date_reponse.strftime('%d/%m/%Y') if response.date_reponse else None,
                'rappels': list(rappels),
                'email': destination.email or '',
                'response_file': response_file_url,
                'response_id': response.id,
                'approval_status': response.approval_status if hasattr(response, 'approval_status') else 'pending',
                'revision_comments': response.revision_comments if hasattr(response, 'revision_comments') else None,
            })
        except Exception as e:
            logger.error("Error processing destination %s for lettre %s: %s", destination.nom, pk, str(e))
            continue

    today = datetime.now().date()
    days_overdue = (today - lettre.deadline).days if lettre.deadline and today > lettre.deadline else 0
    days_until_deadline = (lettre.deadline - today).days if lettre.deadline and today <= lettre.deadline else 0

    # Handle image_file
    image_url = lettre.image_file.url if hasattr(lettre, 'image_file') and lettre.image_file else None

    # Prepare service data
    service_data = lettre.get_service_display() if hasattr(lettre, 'get_service_display') else (lettre.service or 'N/A')

    # Construct response data
    data = {
        'success': True,
        'subject': lettre.subject,
        'category': lettre.category,
        'date': lettre.date.strftime('%d/%m/%Y') if lettre.date else None,
        'deadline': lettre.deadline.strftime('%d/%m/%Y') if lettre.deadline else None,
        'priority': lettre.priority,
        'get_priority_display': lettre.get_priority_display(),
        'statut': lettre.statut,
        'get_statut_display': lettre.get_statut_display(),
        'destinations': destinations_data,
        'sent_to_all_destinations': lettre.sent_to_all_destinations,
        'days_overdue': days_overdue,
        'days_until_deadline': days_until_deadline,
        'rappels_envoyes': total_rappels_envoyes,
        'response_template': lettre.response_template.url if lettre.response_template else None,
        'image': image_url,
        'created_by': lettre.created_by.username if lettre.created_by else 'Unknown',  # Added created_by field
    }

    # Include service only for super_admin, admin_saisie, admin_reponse
    if profile.role in ['super_admin', 'admin_saisie', 'admin_reponse']:
        data['service'] = service_data

    try:
        return JsonResponse(data, status=200)
    except Exception as e:
        logger.error("Error constructing response data for lettre %s: %s", pk, str(e))
        return JsonResponse({'success': False, 'message': 'Erreur interne lors de la construction des données.'}, status=500)





@login_required
def dashboard_Reponse(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        logger.error(f"UserProfile does not exist for user: {request.user.username}")
        messages.error(request, "Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.")
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.',
            'csrf_token': get_token(request),
        }, status=403)

    # Restrict access to authorized roles
    if profile.role not in ['admin_reponse', 'saisie_er']:
        logger.error(f"Unauthorized access to dashboard by user: {request.user.username}, role: {profile.role}")
        messages.error(request, "Vous n’êtes pas autorisé à accéder à cette interface.")
        return redirect('lettres:dashboard')

    # Ensure destination exists
    destination = profile.destination
    if not destination:
        logger.error(f"No destination associated with user: {request.user.username}")
        messages.error(request, "Aucune destination associée à votre profil.")
        return render(request, 'response_requet/user_dashboard.html', {
            'error': 'Aucune destination associée à votre profil.',
            'user_role': profile.role,
            'csrf_token': get_token(request),
        }, status=403)

    # Fetch responses for the user's destination
    responses = Response.objects.filter(destination=destination).select_related('lettre')
    if profile.role == 'saisie_er':
        responses = responses.filter(lettre__service=profile.service)

    # Update overdue responses
    today = date.today()
    for response in responses.filter(statut='en_attente'):
        if response.lettre.deadline and response.lettre.deadline < today:
            response.statut = 'en_retard'
            response.save(update_fields=['statut'])

    # Compute stats for cards
    total_responses = responses.count()
    responses_en_attente = responses.filter(statut='en_attente')
    responses_repondues = responses.filter(statut='repondu')
    responses_en_retard = responses.filter(statut='en_retard')
    responses_urgent = responses.filter(lettre__priority='high')

    # Calculate completion percentage
    completion_percentage = (responses_repondues.count() / total_responses * 100) if total_responses > 0 else 0

    # Calculate average response time
    temps_moyen_reponse = 0
    if responses_repondues.exists():
        total_hours = sum(
            (response.date_reponse - response.lettre.date).total_seconds() / 3600
            for response in responses_repondues
            if response.date_reponse and response.lettre.date
        )
        temps_moyen_reponse = total_hours / responses_repondues.count() if responses_repondues.count() > 0 else 0

    # Apply filters
    search = request.GET.get('search', '').strip()
    statut_filter = request.GET.get('statut', '')
    categorie_filter = request.GET.get('categorie', '')

    filtered_responses = responses
    if search:
        filtered_responses = filtered_responses.filter(
            Q(lettre__subject__icontains=search) | Q(lettre__description__icontains=search)
        )
    # --- Modified to support 'revision_requested' filter ---
    if statut_filter:
        if statut_filter == 'revision_requested':
            filtered_responses = filtered_responses.filter(approval_status='revision_requested')
        else:
            filtered_responses = filtered_responses.filter(statut=statut_filter)
    if categorie_filter:
        filtered_responses = filtered_responses.filter(lettre__category=categorie_filter)

    # Prepare data for template
    lettres_with_responses = []
    for response in filtered_responses:
        # Compute display_status based on statut and approval_status
        approval_status = response.approval_status if hasattr(response, 'approval_status') else 'pending'
        logger.debug(f"Response ID={response.id}, Statut={response.statut}, Approval={approval_status}")
        if approval_status == 'revision_requested':
            display_status = 'Révision demandée'
        elif response.statut == 'repondu':
            if approval_status == 'pending':
                display_status = 'Soumise'
            elif approval_status == 'accepted':
                display_status = 'Acceptée'
            else:
                display_status = 'Répondu'
        elif response.statut == 'en_retard':
            display_status = 'En retard'
        else:
            display_status = 'En attente'

        lettres_with_responses.append({
            'lettre': response.lettre,
            'response': response,
            'responded_count': Response.objects.filter(lettre=response.lettre, statut='repondu').count(),
            'total_destinations': Response.objects.filter(lettre=response.lettre).count(),
            'created_by': response.lettre.created_by.username if response.lettre.created_by else 'Unknown',
            'display_status': display_status,
            'approval_status': approval_status,
        })

    # Pagination
    paginator = Paginator(lettres_with_responses, 4)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Fetch distinct categories for filter dropdown
    categories = Lettre.objects.filter(
        id__in=responses.values_list('lettre_id', flat=True)
    ).values_list('category', flat=True).distinct()

    context = {
        'page_obj': page_obj,
        'destination': destination,
        'user_role': profile.role,
        'categories': categories,
        'search': search,
        'statut_filter': statut_filter,
        'categorie_filter': categorie_filter,
        'total_responses': total_responses,
        'responses_en_attente': responses_en_attente,
        'responses_repondues': responses_repondues,
        'responses_en_retard': responses_en_retard,
        'responses_urgent': responses_urgent,
        'completion_percentage': round(completion_percentage, 2),
        'temps_moyen_reponse': round(temps_moyen_reponse, 2),
        'csrf_token': get_token(request),
    }
    return render(request, 'response_requet/user_dashboard.html', context)


    
@login_required
def submit_response(request, lettre_id):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        logger.error(f"UserProfile does not exist for user: {request.user.username}")
        return JsonResponse({'success': False, 'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    if profile.role not in ['admin_reponse', 'saisie_er']:
        logger.error(f"Unauthorized access by user: {request.user.username}, role: {profile.role}")
        return JsonResponse({'success': False, 'message': "Vous n'êtes pas autorisé à répondre aux requêtes."}, status=403)

    destination = profile.destination
    if not destination:
        logger.error(f"No destination for user: {request.user.username}")
        return JsonResponse({'success': False, 'message': 'Aucune destination associée à votre profil.'}, status=403)

    lettre = get_object_or_404(Lettre, id=lettre_id)
    if profile.role == 'saisie_er' and lettre.service != profile.service:
        logger.error(f"Service mismatch for user: {request.user.username}, lettre: {lettre.id}")
        return JsonResponse({'success': False, 'message': "Vous ne pouvez répondre qu'aux requêtes de votre service."}, status=403)

    if not (lettre.destinations.filter(id=destination.id).exists() or lettre.sent_to_all_destinations):
        logger.error(f"Unauthorized lettre access by user: {request.user.username}, lettre: {lettre.id}")
        return JsonResponse({'success': False, 'message': "Vous n'êtes pas autorisé à répondre à cette requête."}, status=403)

    # For GET requests, retrieve existing response or initialize empty form
    response = Response.objects.filter(lettre=lettre, destination=destination).first()

    if request.method == 'POST':
        # For POST requests, create or update the response
        if not response:
            response = Response(
                lettre=lettre,
                destination=destination,
                user=None if profile.role == 'admin_reponse' else request.user,
                statut='en_attente'
            )
        form = ResponseForm(request.POST, request.FILES, instance=response, lettre=lettre)
        if form.is_valid():
            response = form.save(commit=False)
            response_file = form.cleaned_data.get('response_file')
            # --- Added logging for debugging ---
            logger.debug(f"Processing response for lettre {lettre.id}, response_file: {response_file}")
            if response_file:
                response.statut = 'repondu'
                response.date_reponse = datetime.now().date()
                response.temps_reponse = math.floor((datetime.now().date() - lettre.date).days * 24)
                response.approval_status = 'pending'
                response.revision_comments = ''
            else:
                response.statut = 'en_attente'
            response.user = None if profile.role == 'admin_reponse' else request.user
            try:
                response.save()
                logger.info(f"Response saved: ID={response.id}, File={response.response_file.path if response.response_file else None}, Statut={response.statut}, Approval={response.approval_status}")
            except Exception as e:
                logger.error(f"Failed to save response: {str(e)}")
                return JsonResponse({'success': False, 'message': f'Erreur lors de l\'enregistrement: {str(e)}'}, status=500)

            # Update lettre status
            expected_response_count = Destination.objects.count() if lettre.sent_to_all_destinations else lettre.destinations.count()
            responded_count = lettre.reponses.filter(statut='repondu').count()
            logger.debug(f"Lettre: {lettre.id}, Expected: {expected_response_count}, Responded: {responded_count}")
            if responded_count >= expected_response_count and expected_response_count > 0:
                lettre.statut = 'repondu'
            elif lettre.is_overdue:
                lettre.statut = 'en_retard'
            else:
                lettre.statut = 'en_attente'
            try:
                lettre.save()
                logger.info(f"Lettre status updated: {lettre.id}, new status: {lettre.statut}")
            except Exception as e:
                logger.error(f"Failed to save lettre: {str(e)}")
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
            logger.error(f"Form errors: {form.errors.as_json()}")
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
        # For GET requests, initialize form with existing response (if any)
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

    # Handle AJAX request for modal
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        lettre = response.lettre
        today = datetime.now().date()
        days_overdue = (today - lettre.deadline).days if lettre.deadline and today > lettre.deadline else 0
        days_until_deadline = (lettre.deadline - today).days if lettre.deadline and today <= lettre.deadline else 0

        # Debug image_file field
        image_url = None
        if hasattr(lettre, 'image_file') and lettre.image_file:
            try:
                image_url = lettre.image_file.url
                logger.debug("Image URL for lettre %s: %s", lettre.id, image_url)
            except Exception as e:
                logger.error("Error accessing image_file URL for lettre %s: %s", lettre.id, str(e))
                image_url = None
        else:
            logger.debug("No image_file field or image_file is None for lettre %s", lettre.id)

        try:
            data = {
                'success': True,
                'subject': lettre.subject,
                'category': lettre.category,
                'service': lettre.service if isinstance(lettre.service, str) else str(lettre.service),
                'date': lettre.date.strftime('%d/%m/%Y') if lettre.date else None,
                'deadline': lettre.deadline.strftime('%d/%m/%Y') if lettre.deadline else None,
                'priority': lettre.priority,
                'get_priority_display': lettre.get_priority_display(),
                'statut': response.statut,
                'get_statut_display': response.get_statut_display(),
                'commentaires': response.commentaires or 'Aucun commentaire',
                'days_overdue': days_overdue,
                'days_until_deadline': days_until_deadline,
                'response_file': response.response_file.url if response.response_file else None,
                'response_template': lettre.response_template.url if lettre.response_template else None,
                'image': image_url,  # Include image_file URL
                'approval_status': response.approval_status,
                'revision_comments': response.revision_comments,
            }
            return JsonResponse(data, status=200)
        except Exception as e:
            logger.error("Error constructing response data for response %s: %s", response.id, str(e))
            return JsonResponse({'success': False, 'message': 'Erreur interne lors de la construction des données.'}, status=500)

    context = {
        'response': response,
        'lettre': response.lettre,
        'destination': profile.destination,
        'user_role': profile.role,
    }
    return render(request, 'response_requet/response_detail.html', context)

@login_required
def approve_response(request, response_id):
    profile = request.user.userprofile
    if profile.role not in ['super_admin', 'admin_saisie', 'saisie_ec']:
        return JsonResponse({'success': False, 'message': "Vous n'êtes pas autorisé à approuver les réponses."}, status=403)

    response = get_object_or_404(Response, id=response_id)
    if profile.role == 'saisie_ec' and response.lettre.service != profile.service:
        return JsonResponse({'success': False, 'message': "Vous ne pouvez approuver que les réponses de votre service."}, status=403)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            approval_status = data.get('approval_status')
            revision_comments = data.get('revision_comments', '')
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

        if approval_status not in dict(Response.APPROVAL_CHOICES):
            return JsonResponse({'success': False, 'message': 'Invalid approval status'}, status=400)

        response.approval_status = approval_status
        response.revision_comments = revision_comments

        # --- Modified to set statut to 'en_attente' for revision_requested ---
        if approval_status == 'revision_requested':
            if not revision_comments:
                return JsonResponse({'success': False, 'message': 'Comments required for revision'}, status=400)
            response.statut = 'en_attente'  # Set to 'en_attente' to indicate further action needed
            # Send email notification for revision request
            subject = f"Révision demandée pour {response.lettre.subject}"
            message = f"Révision demandée pour la requête: {response.lettre.subject}.\nCommentaires: {revision_comments}\nVeuillez resoumettre."
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [response.destination.email])
        elif approval_status == 'accepted':
            response.statut = 'repondu'

        try:
            response.save()
            logger.info(f"Response updated: ID={response.id}, Statut={response.statut}, Approval={response.approval_status}")
        except Exception as e:
            logger.error(f"Failed to save response: {str(e)}")
            return JsonResponse({'success': False, 'message': f'Erreur lors de l\'enregistrement: {str(e)}'}, status=500)

        # Update lettre status
        lettre = response.lettre
        all_accepted = all(r.approval_status == 'accepted' for r in lettre.reponses.all() if r.statut == 'repondu')
        # --- Modified to handle revision_requested in lettre status ---
        if all_accepted:
            lettre.statut = 'repondu'
        elif any(r.approval_status == 'revision_requested' for r in lettre.reponses.all()):
            lettre.statut = 'en_attente'
        elif lettre.is_overdue:
            lettre.statut = 'en_retard'
        else:
            lettre.statut = 'en_attente'
        try:
            lettre.save()
            logger.info(f"Lettre status updated: {lettre.id}, new status: {lettre.statut}")
        except Exception as e:
            logger.error(f"Failed to save lettre: {str(e)}")
            return JsonResponse({'success': False, 'message': f'Erreur lors de la mise à jour de la lettre: {str(e)}'}, status=500)

        return JsonResponse({'success': True, 'message': 'Statut mis à jour.'})
    
    return JsonResponse({'success': False, 'message': 'Méthode non autorisée.'}, status=405)
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

    # Paginate destinations
    destinations_list = Destination.objects.all().order_by('nom')
    paginator = Paginator(destinations_list, 10)  # 10 destinations per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    if request.method == 'POST':
        if 'delete_destination' in request.POST:
            # Handle deletion
            destination_id = request.POST.get('destination_id')
            destination = get_object_or_404(Destination, id=destination_id)
            try:
                destination.delete()
                messages.success(request, 'Destination supprimée avec succès.')
            except IntegrityError:
                messages.error(request, 'Erreur : Impossible de supprimer cette destination car elle est utilisée ailleurs.')
            return redirect('lettres:destinations')

        elif 'edit_destination' in request.POST:
            # Handle editing
            destination_id = request.POST.get('destination_id')
            destination = get_object_or_404(Destination, id=destination_id)
            form = DestinationForm(request.POST, instance=destination)
            if form.is_valid():
                try:
                    form.save()
                    messages.success(request, 'Destination modifiée avec succès.')
                    return redirect('lettres:destinations')
                except IntegrityError:
                    messages.error(request, 'Erreur : Cette destination existe déjà.')
            else:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f"{field}: {error}")

        else:
            # Handle adding new destination
            form = DestinationForm(request.POST)
            if form.is_valid():
                try:
                    form.save()
                    messages.success(request, 'Destination ajoutée avec succès.')
                    return redirect('lettres:destinations')
                except IntegrityError:
                    messages.error(request, 'Erreur : Cette destination existe déjà.')
            else:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f"{field}: {error}")

    context = {
        'page_obj': page_obj,
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
def archive(request):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        logger.error("UserProfile does not exist for user: %s", request.user.username)
        return render(request, 'error.html', {
            'error': 'Votre compte n’a pas de profil utilisateur configuré. Contactez l’administrateur.'
        })

    # Define cutoff dates
    one_year_ago = datetime.now().date() - timedelta(days=365)
    one_month_ago = datetime.now().date() - timedelta(days=30)

    # Base query for archived letters
    lettres = Lettre.objects.filter(
        Q(statut__in=['en_attente', 'en_retard'], deadline__lte=one_year_ago) |
        Q(statut='repondu', reponses__date_reponse__lte=one_month_ago)
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
        last_response = lettre.reponses.filter(statut='repondu').order_by('-date_reponse').first()
        lettres_with_data.append({
            'lettre': lettre,
            'last_response_date': last_response.date_reponse if last_response else None
        })

    # Paginate lettres
    paginator = Paginator(lettres_with_data, 8)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'user_role': profile.role,
        'csrf_token': get_token(request),
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
        logger.error("UserProfile does not exist for user: %s", request.user.username)
        return JsonResponse({'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    if profile.role not in ['super_admin', 'admin_saisie', 'saisie_ec']:
        logger.error("Unauthorized access to send reminder by user: %s, role: %s", request.user.username, profile.role)
        return JsonResponse({'message': "Vous n'êtes pas autorisé à envoyer des rappels."}, status=403)

    lettre = get_object_or_404(Lettre, pk=pk)

    # Restrict saisie_ec to their own service and destination
    if profile.role == 'saisie_ec':
        if lettre.service != profile.service:
            logger.error("Service mismatch for user: %s, lettre: %s", request.user.username, lettre.id)
            return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre service."}, status=403)
        if not (lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations):
            logger.error("Destination mismatch for user: %s, lettre: %s", request.user.username, lettre.id)
            return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre destination."}, status=403)

    try:
        data = json.loads(request.body)
        destination_name = data.get('destination')
        if not destination_name:
            logger.error("No destination provided for lettre: %s", lettre.id)
            return JsonResponse({'message': "Nom de la destination manquant."}, status=400)

        destination = get_object_or_404(Destination, nom__iexact=destination_name)
        
        # Additional check for saisie_ec to ensure destination matches
        if profile.role == 'saisie_ec' and destination != profile.destination:
            logger.error("Unauthorized destination %s for user: %s", destination_name, request.user.username)
            return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre destination."}, status=403)

        if not (lettre.destinations.filter(id=destination.id).exists() or lettre.sent_to_all_destinations):
            logger.error("Destination %s not associated with lettre: %s", destination_name, lettre.id)
            return JsonResponse({'message': f"Cette destination {destination_name} n'est pas associée à la requête."}, status=403)

        response = Response.objects.filter(lettre=lettre, destination=destination).first()
        if not response:
            response = Response.objects.create(
                lettre=lettre,
                destination=destination,
                statut='en_attente'
            )
            logger.info("Created new Response for lettre %s, destination %s", lettre.id, destination_name)

        if response.statut != 'en_attente':
            logger.info("Response for lettre %s, destination %s is already %s", lettre.id, destination_name, response.statut)
            return JsonResponse({'message': f"La réponse pour {destination_name} est déjà {response.get_statut_display()}."}, status=400)

        if not destination.email:
            logger.error("No email configured for destination: %s", destination_name)
            return JsonResponse({'message': f"Aucun email configuré pour {destination_name}."}, status=400)

        subject = f"Rappel: {lettre.subject}"
        message = f"Rappel pour la requête: {lettre.subject}. Veuillez répondre avant {lettre.deadline}."
        try:
            send_mail(
                subject=subject,
                message=message,
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
            logger.info("Reminder sent for lettre %s to %s", lettre.id, destination_name)
            return JsonResponse({'message': f"Rappel envoyé avec succès à {destination_name}."})
        except Exception as e:
            logger.error("Failed to send email to %s for lettre %s: %s", destination_name, lettre.id, str(e))
            rappel = Rappel.objects.create(
                response=response,
                type='email',
                date=datetime.now().date(),
                time=datetime.now().time(),
                message=f"Rappel pour {lettre.subject}",
                status='failed'
            )
            response.rappels.add(rappel)
            response.save()
            return JsonResponse({'message': f"Erreur lors de l'envoi de l'email à {destination_name}: {str(e)}"}, status=500)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body for lettre: %s", pk)
        return JsonResponse({'message': "Données de requête invalides."}, status=400)
    except Destination.DoesNotExist:
        logger.error("Destination %s not found for lettre: %s", destination_name, pk)
        return JsonResponse({'message': f"Destination {destination_name} introuvable."}, status=404)
    except Exception as e:
        logger.error("Unexpected error in send_email_reminder for lettre %s: %s", pk, str(e))
        return JsonResponse({'message': f"Erreur inattendue: {str(e)}"}, status=500)


@login_required
@require_POST
def send_global_reminder(request, pk):
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return JsonResponse({'message': 'Votre compte n’a pas de profil utilisateur configuré.'}, status=403)

    if profile.role not in ['super_admin', 'admin_saisie', 'saisie_ec']:
        return JsonResponse({'message': "Vous n'êtes pas autorisé à envoyer des rappels."}, status=403)

    lettre = get_object_or_404(Lettre, pk=pk)

    # Restrict saisie_ec to their own service and destination
    if profile.role == 'saisie_ec':
        if lettre.service != profile.service:
            return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre service."}, status=403)
        if not (lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations):
            return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre destination."}, status=403)

        # Single reminder for saisie_ec user's destination
        destination = profile.destination
        if not destination.email:
            return JsonResponse({'message': f"Aucun email configuré pour {destination.nom}."}, status=400)

        response = Response.objects.filter(lettre=lettre, destination=destination).first()
        if not response:
            response = Response.objects.create(lettre=lettre, destination=destination, statut='en_attente')

        if response.statut != 'en_attente':
            return JsonResponse({'message': f"La destination {destination.nom} a déjà répondu."}, status=400)

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
            return JsonResponse({'message': f"Rappel envoyé avec succès à {destination.nom}."})
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
            lettre.save()
            return JsonResponse({'message': f"Erreur lors de l'envoi du rappel à {destination.nom}: {str(e)}"}, status=500)

    # Global reminder logic for super_admin and admin_saisie
    if profile.role == 'admin_saisie' and not (lettre.destinations.filter(id=profile.destination.id).exists() or lettre.sent_to_all_destinations):
        return JsonResponse({'message': "Vous ne pouvez envoyer des rappels que pour votre destination."}, status=403)

    destinations = (
        Destination.objects.all() if lettre.sent_to_all_destinations else lettre.destinations.all()
    )

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
        lettres = lettres.filter(service=profile.service, destinations=profile.destination)
    elif profile.role == 'admin_saisie':
        lettres = lettres.filter(Q(destinations=profile.destination) | Q(sent_to_all_destinations=True))

    reminder_count = 0
    errors = []

    for lettre in lettres:
        last_reminder = lettre.date_dernier_rappel
        now = datetime.now().date()
        if last_reminder and (now - last_reminder).days < settings.reminder_frequency / 24:
            continue

        # For saisie_ec, limit to their own destination
        destinations = (
            Destination.objects.filter(id=profile.destination.id)
            if profile.role == 'saisie_ec'
            else Destination.objects.all() if lettre.sent_to_all_destinations else lettre.destinations.all()
        )

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
        logger.error(f"UserProfile not found for user {request.user.username}")
        messages.error(request, "Votre compte n'a pas de profil utilisateur configuré. Veuillez contacter l'administrateur.")
        return render(request, 'error.html', {
            'error': "Votre compte n'a pas de profil utilisateur configuré. Veuillez contacter l'administrateur."
        })

    if profile.role != 'super_admin':
        logger.warning(f"Unauthorized access to settings by user {request.user.username} with role {profile.role}")
        messages.error(request, "Vous n'avez pas les autorisations nécessaires pour accéder aux paramètres.")
        return redirect('lettres:dashboard')

    settings, created = SystemSettings.objects.get_or_create(user=request.user)
    form = SystemSettingsForm(instance=settings)
    user_form = UserCreationForm()
    destination_form = DestinationForm()
    edit_user_form = UserProfileForm()
    users = UserProfile.objects.all()
    destinations = Destination.objects.all()

    if request.method == 'POST':
        if 'save_settings' in request.POST:
            form = SystemSettingsForm(request.POST, instance=settings)
            if form.is_valid():
                form.save()
                messages.success(request, "Les paramètres ont été enregistrés avec succès.")
                logger.info(f"System settings updated by user {request.user.username}")
                return redirect('lettres:settings?tab=notifications')
            else:
                messages.error(request, "Erreur lors de l'enregistrement des paramètres. Veuillez vérifier les informations saisies.")
                logger.error(f"System settings form errors: {form.errors}")

        elif 'add_user' in request.POST:
            user_form = UserCreationForm(request.POST, request.FILES)
            if user_form.is_valid():
                try:
                    user = user_form.save()
                    messages.success(request, f"L'utilisateur '{user.username}' a été ajouté avec succès.")
                    logger.info(f"User {user.username} created by {request.user.username}")
                    return redirect('lettres:settings?tab=users')
                except Exception as e:
                    messages.error(request, "Une erreur est survenue lors de la création de l'utilisateur. Veuillez réessayer.")
                    logger.error(f"Error creating user: {str(e)}")
            else:
                messages.error(request, "Erreur lors de la création de l'utilisateur. Veuillez vérifier les informations saisies.")
                logger.error(f"User creation form errors: {user_form.errors}")

        elif 'edit_user' in request.POST:
            user_id = request.POST.get('user_id')
            try:
                user_profile = UserProfile.objects.get(user__id=user_id)
                edit_user_form = UserProfileForm(request.POST, request.FILES, instance=user_profile)
                if edit_user_form.is_valid():
                    edit_user_form.save()
                    messages.success(request, f"Le profil de l'utilisateur '{user_profile.user.username}' a été modifié avec succès.")
                    logger.info(f"User {user_profile.user.username} profile edited by {request.user.username}")
                    return redirect('lettres:settings?tab=users')
                else:
                    messages.error(request, "Erreur lors de la modification de l'utilisateur. Veuillez vérifier les informations saisies.")
                    logger.error(f"Edit user form errors: {edit_user_form.errors}")
            except UserProfile.DoesNotExist:
                messages.error(request, "L'utilisateur sélectionné n'existe pas.")
                logger.error(f"UserProfile with ID {user_id} not found")
                return redirect('lettres:settings?tab=users')

        elif 'delete_user' in request.POST:
            user_id = request.POST.get('user_id')
            try:
                user_profile = UserProfile.objects.get(user__id=user_id)
                if user_profile.role == 'super_admin':
                    messages.error(request, "Le Super Administrateur ne peut pas être supprimé.")
                    logger.warning(f"Attempt to delete super_admin by {request.user.username}")
                else:
                    user = user_profile.user
                    user_profile.delete()
                    user.delete()
                    messages.success(request, "L'utilisateur a été supprimé avec succès.")
                    logger.info(f"User {user.username} deleted by {request.user.username}")
                return redirect('lettres:settings?tab=users')
            except UserProfile.DoesNotExist:
                messages.error(request, "L'utilisateur sélectionné n'existe pas.")
                logger.error(f"UserProfile with ID {user_id} not found")
                return redirect('lettres:settings?tab=users')

        elif 'add_destination' in request.POST:
            destination_form = DestinationForm(request.POST)
            if destination_form.is_valid():
                try:
                    destination_form.save()
                    messages.success(request, "La destination a été ajoutée avec succès.")
                    logger.info(f"Destination added by {request.user.username}")
                    return redirect('lettres:settings?tab=destinations')
                except Exception as e:
                    messages.error(request, "Une erreur est survenue lors de l'ajout de la destination. Veuillez réessayer.")
                    logger.error(f"Error adding destination: {str(e)}")
            else:
                messages.error(request, "Erreur lors de l'ajout de la destination. Veuillez vérifier les informations saisies.")
                logger.error(f"Destination form errors: {destination_form.errors}")

        elif 'edit_destination' in request.POST:
            destination_id = request.POST.get('destination_id')
            try:
                destination = Destination.objects.get(id=destination_id)
                destination_form = DestinationForm(request.POST, instance=destination)
                if destination_form.is_valid():
                    destination_form.save()
                    messages.success(request, "La destination a été modifiée avec succès.")
                    logger.info(f"Destination {destination_id} edited by {request.user.username}")
                    return redirect('lettres:settings?tab=destinations')
                else:
                    messages.error(request, "Erreur lors de la modification de la destination. Veuillez vérifier les informations saisies.")
                    logger.error(f"Edit destination form errors: {destination_form.errors}")
            except Destination.DoesNotExist:
                messages.error(request, "La destination sélectionnée n'existe pas.")
                logger.error(f"Destination with ID {destination_id} not found")
                return redirect('lettres:settings?tab=destinations')

        elif 'delete_destination' in request.POST:
            destination_id = request.POST.get('destination_id')
            try:
                destination = Destination.objects.get(id=destination_id)
                destination.delete()
                messages.success(request, "La destination a été supprimée avec succès.")
                logger.info(f"Destination {destination_id} deleted by {request.user.username}")
                return redirect('lettres:settings?tab=destinations')
            except Destination.DoesNotExist:
                messages.error(request, "La destination sélectionnée n'existe pas.")
                logger.error(f"Destination with ID {destination_id} not found")
                return redirect('lettres:settings?tab=destinations')

    context = {
        'form': form,
        'user_form': user_form,
        'edit_user_form': edit_user_form,
        'destination_form': destination_form,
        'users': users,
        'destinations': destinations,
        'user_role': profile.role,
        'active_tab': request.GET.get('tab', 'notifications'),
    }
    return render(request, 'menu/settings.html', context)


  
logger = logging.getLogger(__name__)


@shared_task
def send_reminders():

    logger.info("Starting send_reminders task")

    # Retrieve system settings (use first() or create defaults if none exist)
    system_settings = SystemSettings.objects.first()
    if not system_settings:
        logger.warning("No SystemSettings found, creating default settings")
        system_settings = SystemSettings.objects.create(
            email_notifications=True,
            reminder_frequency=24,  # Default: 24 hours
            escalation_time=48,    # Default: 48 hours
            archive_in_progress_after_year=False,
            archive_closed_after_month=False
        )

    if not system_settings.email_notifications:
        logger.info("Email notifications are disabled in SystemSettings")
        return

    # Get all pending lettres
    lettres = Lettre.objects.filter(statut="en_attente")
    logger.info(f"Found {lettres.count()} pending lettres")

    reminder_count = 0
    errors = []

    for lettre in lettres:
        # Check the last reminder sent for this lettre
        last_rappel = lettre.rappels.order_by('-date').first()
        now = timezone.now().date()

        # Skip if the last reminder was sent too recently
        if last_rappel:
            hours_since = (timezone.now() - last_rappel.date).total_seconds() / 3600
            logger.debug(f"Lettre {lettre.id}: {hours_since} hours since last reminder")
            if hours_since < system_settings.reminder_frequency:
                logger.debug(f"Skipping lettre {lettre.id}: Reminder sent too recently")
                continue

        # Determine destinations for this lettre
        destinations = Destination.objects.all() if lettre.sent_to_all_destinations else lettre.destinations.all()

        for destination in destinations:
            # Get or create a response for this destination
            response, created = Response.objects.get_or_create(
                lettre=lettre,
                destination=destination,
                defaults={'statut': 'en_attente'}
            )

            # Skip if the response is not pending
            if response.statut != 'en_attente':
                logger.debug(f"Skipping response for lettre {lettre.id}, destination {destination.nom}: Already {response.statut}")
                continue

            # Skip if destination has no email
            if not destination.email:
                logger.warning(f"No email configured for destination {destination.nom}")
                errors.append(f"Aucun email pour {destination.nom}")
                continue

            try:
                # Send reminder email
                subject = f"Rappel Automatique: {lettre.subject}"
                message = (
                    f"Rappel automatique pour la requête: {lettre.subject}.\n"
                    f"Veuillez répondre avant le {lettre.deadline.strftime('%d/%m/%Y')}."
                )
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[destination.email],
                    fail_silently=False,
                )

                # Create a rappel record
                rappel = Rappel.objects.create(
                    response=response,
                    type='email',
                    date=now,
                    time=timezone.now().time(),
                    message=f"Rappel automatique pour {lettre.subject}",
                    status='sent'
                )
                response.rappels.add(rappel)
                lettre.rappels_envoyes += 1
                lettre.date_dernier_rappel = now
                lettre.save()
                response.save()
                reminder_count += 1
                logger.info(f"Reminder sent for lettre {lettre.id} to {destination.nom}")

            except Exception as e:
                # Log and record failed rappel
                logger.error(f"Failed to send reminder for lettre {lettre.id} to {destination.nom}: {str(e)}")
                rappel = Rappel.objects.create(
                    response=response,
                    type='email',
                    date=now,
                    time=timezone.now().time(),
                    message=f"Rappel automatique pour {lettre.subject}",
                    status='failed'
                )
                response.rappels.add(rappel)
                response.save()
                errors.append(f"Erreur pour {destination.nom}: {str(e)}")

    # Log the outcome
    if errors:
        logger.warning(f"Sent {reminder_count} reminders with errors: {', '.join(errors)}")
    else:
        logger.info(f"Successfully sent {reminder_count} reminders")

    return {
        'reminder_count': reminder_count,
        'errors': errors
    }
