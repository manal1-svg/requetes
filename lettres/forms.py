import os
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm
from django.contrib.auth.models import User
from django.middleware.csrf import logger

from .models import Lettre, Destination, Response, SystemSettings, UserProfile


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Nom d’utilisateur'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Mot de passe'
        })
    )
    
class LettreForm(forms.ModelForm):
    def __init__(self, *args, user_profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user_profile:
            logger.debug(f"User profile role: {user_profile.role}, service: {user_profile.service}, destination: {user_profile.destination}")
            # Set initial service with fallback
            valid_services = dict(Lettre.SERVICE_CHOICES)
            if user_profile.service and user_profile.service in valid_services:
                self.fields['service'].initial = user_profile.service
            else:
                self.fields['service'].initial = 'SGP'
                logger.warning(f"Invalid or missing service for user {user_profile.user.username}, defaulting to SGP")
            # Set initial destination with fallback
            if user_profile.role in ['saisie_ec', 'admin_saisie', 'directeur_regional']:
                if user_profile.destination and hasattr(user_profile.destination, 'id'):
                    self.fields['destinations'].initial = [user_profile.destination.id]
                    self.fields['destinations'].disabled = True
                    self.fields['destinations'].widget.attrs['disabled'] = 'disabled'
                    self.fields['destinations'].widget = forms.HiddenInput()
                    self.fields['sent_to_all_destinations'].disabled = True
                    self.fields['sent_to_all_destinations'].widget.attrs['disabled'] = 'disabled'
                    logger.debug(f"Destinations field disabled and set to {user_profile.destination} for {user_profile.role} user")
                else:
                    default_destination = Destination.objects.first()
                    if default_destination:
                        self.fields['destinations'].initial = [default_destination.id]
                        logger.warning(f"No destination for user {user_profile.user.username}, defaulting to {default_destination}")
                    else:
                        logger.error("No destinations available to set as default")
                        raise ValidationError("Aucune destination disponible pour configuration.")
            else:
                logger.debug("Service and destinations fields enabled for other users")

    destinations = forms.ModelMultipleChoiceField(
        queryset=Destination.objects.all(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'destination-checkbox h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
        required=False
    )
    category = forms.ChoiceField(
        choices=Lettre.CATEGORY_CHOICES,
        widget=forms.Select(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md', 'id': 'category'}),
        required=True
    )
    service = forms.ChoiceField(
        choices=Lettre.SERVICE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
        required=True
    )
    format = forms.ChoiceField(
        choices=Lettre.FORMAT_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
        required=True
    )
    priority = forms.ChoiceField(
        choices=Lettre.PRIORITY_CHOICES,
        widget=forms.HiddenInput(attrs={'id': 'priority'}),
        required=True,
        initial='medium'
    )

    class Meta:
        model = Lettre
        fields = [
            'subject', 'category', 'date', 'deadline', 'destinations',
            'sent_to_all_destinations', 'service', 'format', 'priority',
            'description', 'image_file', 'response_template'
        ]
        widgets = {
            'subject': forms.TextInput(attrs={
                'class': 'w-full p-2 border border-gray-300 rounded-md',
                'id': 'subject',
                'placeholder': 'Sujet'
            }),
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full p-2 border border-gray-300 rounded-md',
                'id': 'date'
            }),
            'deadline': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full p-2 border border-gray-300 rounded-md',
                'id': 'deadline'
            }),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full p-2 border border-gray-300 rounded-md',
                'id': 'description',
                'placeholder': 'Description'
            }),
            'sent_to_all_destinations': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500',
                'id': 'all-destinations'
            }),
            'image_file': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'hidden',
                'id': 'image-upload'
            }),
            'response_template': forms.FileInput(attrs={
                'accept': '.xlsx,.xls,.pdf',
                'class': 'hidden',
                'id': 'template-upload'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        service = cleaned_data.get('service')
        destinations = cleaned_data.get('destinations')
        sent_to_all_destinations = cleaned_data.get('sent_to_all_destinations')

        # Ensure at least one destination is selected or sent_to_all_destinations is checked
        if not sent_to_all_destinations and not destinations:
            logger.error("Validation failed: No destinations selected and sent_to_all_destinations not checked")
            raise ValidationError("Veuillez sélectionner au moins une destination ou cocher 'Envoyé à toutes les destinations'.")

        # Validate MARITIME service restriction
        if service == 'MARITIME' and not sent_to_all_destinations:
            valid_destinations = Destination.objects.filter(nom__in=['Nador', 'Driouch'])
            if not all(destination in valid_destinations for destination in destinations):
                logger.error("Validation failed: MARITIME service selected with invalid destinations")
                raise ValidationError("Le service MARITIME est uniquement disponible pour Nador ou Driouch.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        destinations = self.cleaned_data.get('destinations')
        sent_to_all_destinations = self.cleaned_data.get('sent_to_all_destinations')

        if commit:
            instance.save()
            instance.destinations.clear()
            if sent_to_all_destinations:
                instance.destinations.set(Destination.objects.all())
            else:
                instance.destinations.set(destinations)
            instance.save()
        return instance

        
class DestinationForm(forms.ModelForm):
    class Meta:
        model = Destination
        fields = ['nom', 'telephone', 'email']
        widgets = {
            'nom': forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2'}),
            'telephone': forms.TextInput(attrs={'class': 'w-full border border-gray-300 rounded-md p-2', 'placeholder': 'Numéro de téléphone'}),
            'email': forms.EmailInput(attrs={'class': 'w-full border border-gray-300 rounded-md p-2', 'placeholder': 'Adresse e-mail'}),
        }
        labels = {
            'nom': 'Nom de la destination',
            'telephone': 'Numéro de téléphone',
            'email': 'Adresse e-mail',
        }


class ResponseForm(forms.ModelForm):
    def __init__(self, *args, lettre=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lettre = lettre
        self.fields['commentaires'].required = False
        self.fields['statut'].required = True
        self.fields['date_reponse'].required = True
        self.fields['temps_reponse'].required = False
        self.fields['response_file'].required = False  # Optional, like image_file/response_template

    class Meta:
        model = Response
        fields = ['statut', 'date_reponse', 'temps_reponse', 'commentaires', 'response_file']
        widgets = {
            'commentaires': forms.Textarea(attrs={
                'rows': 4,
                'class': 'w-full p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'Entrez vos commentaires ici...',
                'id': 'commentaires'
            }),
            'response_file': forms.FileInput(attrs={
                'class': 'hidden',
                'id': 'response-file-upload',
                'accept': '.xls,.xlsx,.pdf,.doc,.docx'  # Match LettreForm's response_template
            }),
            'statut': forms.HiddenInput(),
            'date_reponse': forms.HiddenInput(),
            'temps_reponse': forms.HiddenInput(),
        }

    def clean_response_file(self):
        response_file = self.cleaned_data.get('response_file')
        logger.debug("Validating response_file: %s", response_file.name if response_file else None)
        if response_file and self.lettre:
            expected_format = self.lettre.format
            file_ext = os.path.splitext(response_file.name)[1].lower()
            logger.debug("File extension: %s, Expected format: %s", file_ext, expected_format)
            valid_extensions = {
                'Excel': ['.xls', '.xlsx'],
                'PDF': ['.pdf'],
                'Word': ['.doc', '.docx'],
                'Autre': ['.xls', '.xlsx', '.pdf', '.doc', '.docx']  # Allow all for 'Autre'
            }
            allowed_extensions = valid_extensions.get(expected_format)
            if allowed_extensions and file_ext not in allowed_extensions:
                logger.error("Invalid file format: %s, expected: %s", file_ext, allowed_extensions)
                raise forms.ValidationError(
                    f"Le fichier doit être au format {expected_format}: {', '.join(allowed_extensions)}"
                )
        return response_file

    def save(self, commit=True):
        instance = super().save(commit=False)
        logger.debug("Saving Response: lettre=%s, destination=%s, file=%s",
                     self.lettre.id, instance.destination.nom, self.cleaned_data.get('response_file'))
        if commit:
            instance.save()
            logger.info("Response saved: ID=%s", instance.id)
        return instance


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'email_notifications', 'reminder_frequency', 'escalation_time',
            'archive_in_progress_after_year', 'archive_closed_after_month'
        ]
        widgets = {
            'email_notifications': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'reminder_frequency': forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2'}),
            'escalation_time': forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2'}),
            'archive_in_progress_after_year': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'archive_closed_after_month': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
        }
        labels = {
            'email_notifications': 'Notifications par email',
            'reminder_frequency': 'Fréquence des rappels (heures)',
            'escalation_time': 'Escalade après (heures)',
            'archive_in_progress_after_year': 'Archiver les requêtes en cours après 1 an',
            'archive_closed_after_month': 'Archiver les requêtes clôturées après 1 mois',
        }


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['role', 'destination', 'service']
        widgets = {
            'role': forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2'}),
            'destination': forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2'}),
            'service': forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2'}),
        }
        labels = {
            'role': 'Rôle',
            'destination': 'Destination',
            'service': 'Service',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = [
            ('admin_saisie', 'Directeur Régional'),
            ('saisie_ec', 'Responsable Service DR'),
            ('admin_reponse', 'Directeur Provincial'),
            ('saisie_er', 'Responsable Service DP'),
        ]

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        destination = cleaned_data.get('destination')
        service = cleaned_data.get('service')

        if role in ['saisie_ec', 'saisie_er']:
            if not service:
                raise ValidationError("Veuillez sélectionner un service pour ce rôle.")
            if not destination:
                raise ValidationError("Veuillez sélectionner une destination pour ce rôle.")
        elif role == 'admin_reponse':
            if not destination:
                raise ValidationError("Veuillez sélectionner une destination pour le rôle de Directeur Provincial.")
            if service:
                raise ValidationError("Le rôle de Directeur Provincial ne peut pas être associé à un service.")
            if destination and UserProfile.objects.exclude(user__id=self.instance.user_id).filter(role='admin_reponse', destination=destination).exists():
                raise ValidationError(f"Un Directeur Provincial est déjà assigné à la destination {destination.nom}.")
        elif role == 'admin_saisie':
            if not destination:
                raise ValidationError("Veuillez sélectionner une destination pour le rôle de Directeur Régional.")
            if service:
                raise ValidationError("Le rôle de Directeur Régional ne peut pas être associé à un service.")
            if destination and UserProfile.objects.exclude(user__id=self.instance.user_id).filter(role='admin_saisie', destination=destination).exists():
                raise ValidationError(f"Un Directeur Régional est déjà assigné à la destination {destination.nom}.")

        return cleaned_data

class UserCreationForm(BaseUserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'w-full border border-gray-300 rounded-md p-2', 'placeholder': 'Adresse e-mail'})
    )
    role = forms.ChoiceField(
        choices=[
            ('admin_saisie', 'Directeur Régional'),
            ('saisie_ec', 'Responsable Service DR'),
            ('admin_reponse', 'Directeur Provincial'),
            ('saisie_er', 'Responsable Service DP'),
        ],
        required=True,
        widget=forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2', 'id': 'id_role'})
    )
    destination = forms.ModelChoiceField(
        queryset=Destination.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2'})
    )
    service = forms.ChoiceField(
        choices=Lettre.SERVICE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'w-full border border-gray-300 rounded-md p-2'})
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2', 'role', 'destination', 'service']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'w-full border border-gray-300 rounded-md p-2', 'placeholder': "Nom d'utilisateur"}),
            'password1': forms.PasswordInput(attrs={'class': 'w-full border border-gray-300 rounded-md p-2', 'placeholder': 'Mot de passe'}),
            'password2': forms.PasswordInput(attrs={'class': 'w-full border border-gray-300 rounded-md p-2', 'placeholder': 'Confirmation du mot de passe'}),
        }

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise ValidationError("Ce nom d'utilisateur est déjà utilisé. Veuillez en choisir un autre.")
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            raise ValidationError("Cette adresse e-mail est déjà enregistrée. Veuillez utiliser une autre adresse.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        destination = cleaned_data.get('destination')
        service = cleaned_data.get('service')

        if role in ['saisie_ec', 'saisie_er']:
            if not service:
                raise ValidationError("Veuillez sélectionner un service pour ce rôle.")
            if not destination:
                raise ValidationError("Veuillez sélectionner une destination pour ce rôle.")
        elif role == 'admin_reponse':
            if not destination:
                raise ValidationError("Veuillez sélectionner une destination pour le rôle de Directeur Provincial.")
            if service:
                raise ValidationError("Le rôle de Directeur Provincial ne peut pas être associé à un service.")
            if destination and UserProfile.objects.filter(role='admin_reponse', destination=destination).exists():
                raise ValidationError(f"Un Directeur Provincial est déjà assigné à la destination {destination.nom}.")
        elif role == 'admin_saisie':
            if not destination:
                raise ValidationError("Veuillez sélectionner une destination pour le rôle de Directeur Régional.")
            if service:
                raise ValidationError("Le rôle de Directeur Régional ne peut pas être associé à un service.")
            cleaned_data['service'] = None  # Explicitly set service to None
            if destination and UserProfile.objects.filter(role='admin_saisie', destination=destination).exists():
                raise ValidationError(f"Un Directeur Régional est déjà assigné à la destination {destination.nom}.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        role = self.cleaned_data['role']
        destination = self.cleaned_data['destination']
        service = self.cleaned_data['service'] if role in ['saisie_ec', 'saisie_er'] else None

        if commit:
            user.save()
            UserProfile.objects.create(
                user=user,
                role=role,
                destination=destination if role in ['saisie_ec', 'saisie_er', 'admin_reponse', 'admin_saisie'] else None,
                service=service
            )
        return user
