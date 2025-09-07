from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import timedelta
from django.core.validators import EmailValidator
from django.db.models import Q

class Destination(models.Model):
    DESTINATION_CHOICES = [
        ('Oujda-Angad', 'Oujda-Angad'),
        ('Nador', 'Nador'),
        ('Driouch', 'Driouch'),
        ('Berkane', 'Berkane'),
        ('Taourirt', 'Taourirt'),
        ('Guercif', 'Guercif'),
        ('Figuig', 'Figuig'),
    ]

    nom = models.CharField(max_length=100, unique=True, choices=DESTINATION_CHOICES, verbose_name='Nom de la destination')
    telephone = models.CharField(max_length=20, verbose_name='Numéro de téléphone', blank=True)
    email = models.EmailField(verbose_name='Adresse e-mail', blank=True, validators=[EmailValidator()])
   

    def __str__(self):
        return self.nom

    class Meta:
        ordering = ['nom']
        verbose_name = 'Destination'
        verbose_name_plural = 'Destinations'

class Lettre(models.Model):
    PRIORITY_CHOICES = (
        ('low', 'Faible'),
        ('medium', 'Moyenne'),
        ('high', 'Élevée'),
    )
    CATEGORY_CHOICES = (
        ('Financement', 'Financement'),
        ('Rapport', 'Rapport'),
        ('Formation', 'Formation'),
        ('Administrative', 'Administrative'),
        ('Technique', 'Technique'),
        ('Juridique', 'Juridique'),
    )
    SERVICE_CHOICES = (
        ('SGP', 'SGP'),
        ('DRH', 'DRH'),
        ('INFRA', 'INFRA'),
        ('DP', 'DP'),
        ('MARITIME', 'MARITIME'),
    )
    FORMAT_CHOICES = (
        ('Excel', 'Excel'),
        ('PDF', 'PDF'),
        ('Word', 'Word'),
        ('Autre', 'Autre'),
    )
    STATUT_CHOICES = (
        ('en_attente', 'En attente'),
        ('repondu', 'Répondu'),
        ('en_retard', 'En retard'),
    )

    subject = models.CharField(max_length=255, verbose_name='Sujet')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, verbose_name='Catégorie')
    date = models.DateField(verbose_name='Date de réception')
    deadline = models.DateField(verbose_name='Date limite')
    destinations = models.ManyToManyField(Destination, blank=True, verbose_name='Destinations')
    sent_to_all_destinations = models.BooleanField(default=False, verbose_name='Envoyé à toutes les destinations')
    service = models.CharField(max_length=20, choices=SERVICE_CHOICES, verbose_name='Service')
    format = models.CharField(max_length=20, choices=FORMAT_CHOICES, verbose_name='Format')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium', verbose_name='Priorité')
    description = models.TextField(blank=True, verbose_name='Description')
    image_file = models.FileField(upload_to='lettres/images/', null=True, blank=True, verbose_name='Image')
    response_template = models.FileField(upload_to='lettres/templates/', null=True, blank=True, verbose_name='Template de réponse')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créé le')
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente', verbose_name='Statut')
    rappels_envoyes = models.IntegerField(default=0, verbose_name='Rappels envoyés')
    date_dernier_rappel = models.DateField(null=True, blank=True, verbose_name='Date du dernier rappel')
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name='Créé par',
        related_name='lettres_created'  # Useful for reverse relationships
    )

    def __str__(self):
        return f"{self.subject} ({self.get_priority_display()})"

    def update_status(self):
        """Update the lettre status based on deadline and responses."""
        today = timezone.now().date()
        if self.statut != 'repondu' and self.deadline and today > self.deadline:
            self.statut = 'en_retard'
        elif self.statut != 'repondu':
            expected_response_count = Destination.objects.count() if self.sent_to_all_destinations else self.destinations.count()
            responded_count = self.reponses.filter(statut='repondu').count()
            if responded_count >= expected_response_count and expected_response_count > 0:
                self.statut = 'repondu'
            else:
                self.statut = 'en_attente'
        self.save()

    def clean(self):
        if self.pk:
            if not self.destinations.exists() and not self.sent_to_all_destinations:
                raise ValidationError("Au moins une destination doit être sélectionnée ou 'Envoyé à toutes les destinations' doit être coché.")
            if self.service == 'MARITIME' and not self.sent_to_all_destinations:
                valid_destinations = Destination.objects.filter(nom__in=['Nador', 'Driouch'])
                if not all(destination in valid_destinations for destination in self.destinations.all()):
                    raise ValidationError("Le service MARITIME est uniquement disponible pour Nador ou Driouch.")

    def get_days_until_deadline(self):
        today = timezone.now().date()
        diff = self.deadline - today
        return diff.days

    @property
    def is_overdue(self):
        return self.get_days_until_deadline() < 0 and self.statut != 'repondu'

    @property
    def days_overdue(self):
        return abs(self.get_days_until_deadline()) if self.is_overdue else 0

    class Meta:
        ordering = ['-date']
        verbose_name = 'Lettre'
        verbose_name_plural = 'Lettres'

class Response(models.Model):
    STATUT_CHOICES = (
        ('en_attente', 'En attente'),
        ('repondu', 'Répondu'),
        ('en_retard', 'En retard'),
    )
    APPROVAL_CHOICES = [
        ('pending', 'En attente '),
        ('accepted', 'Acceptée'),
        ('revision_requested', 'Révision demandée'),
    ]
    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='pending')
    revision_comments = models.TextField(blank=True)

    lettre = models.ForeignKey(Lettre, on_delete=models.CASCADE, related_name='reponses', verbose_name='Lettre')
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, verbose_name='Destination')
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True, verbose_name='Utilisateur')
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente', verbose_name='Statut')
    date_reponse = models.DateField(blank=True, null=True, verbose_name='Date de réponse')
    temps_reponse = models.IntegerField(blank=True, null=True, verbose_name='Temps de réponse (heures)')
    commentaires = models.TextField(blank=True, null=True, verbose_name='Commentaires')
    response_file = models.FileField(upload_to='responses/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créé le')

    def __str__(self):
        return f"{self.lettre.subject} - {self.destination.nom} - {self.user.username if self.user else 'Admin'}"

    class Meta:
        unique_together = ('lettre', 'destination')
        ordering = ['destination__nom', 'created_at']
        verbose_name = 'Réponse régionale'
        verbose_name_plural = 'Réponses régionales'

        
class Rappel(models.Model):
    TYPE_CHOICES = [
        ('email', 'Email'),
    ]
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ]

    response = models.ForeignKey(Response, on_delete=models.CASCADE, related_name='rappels', verbose_name='Réponse')
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, verbose_name='Type')
    date = models.DateField(verbose_name='Date')
    time = models.TimeField(verbose_name='Heure')
    message = models.TextField(verbose_name='Message')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='sent', verbose_name='Statut')

    def __str__(self):
        return f"{self.type} rappel for {self.response}"

    class Meta:
        verbose_name = 'Rappel'
        verbose_name_plural = 'Rappels'

class SystemSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name='Utilisateur')
    email_notifications = models.BooleanField(default=True, verbose_name='Notifications par email')
    reminder_frequency = models.IntegerField(default=24, choices=[(24, '24 heures'), (48, '48 heures'), (72, '72 heures')], verbose_name='Fréquence des rappels (heures)')
    escalation_time = models.IntegerField(default=72, choices=[(48, '48 heures'), (72, '72 heures'), (96, '96 heures')], verbose_name='Escalade après (heures)')
    archive_in_progress_after_year = models.BooleanField(default=True, verbose_name='Archiver les requêtes en cours après 1 an')
    archive_closed_after_month = models.BooleanField(default=True, verbose_name='Archiver les requêtes clôturées après 1 mois')

    def __str__(self):
        return f"Paramètres de {self.user.username}"

    class Meta:
        verbose_name = 'Paramètres du système'
        verbose_name_plural = 'Paramètres du système'

class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('super_admin', 'Super Administrateur'),
        ('admin_saisie', 'Directeur Régional'),
        ('saisie_ec', 'Responsable Service DR'),
        ('admin_reponse', 'Directeur Provincial'),
        ('saisie_er', 'Responsable Service DP'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name='Utilisateur')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, verbose_name='Rôle')
    destination = models.ForeignKey(Destination, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Destination')
    service = models.CharField(max_length=20, choices=Lettre.SERVICE_CHOICES, null=True, blank=True, verbose_name='Service')
    photo = models.ImageField(upload_to='profiles/', null=True, blank=True, verbose_name='Photo de profil')

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

    def clean(self):
        # Validate photo size and format
        if self.photo:
            if self.photo.size > 2 * 1024 * 1024:  # 2MB limit
                raise ValidationError("La photo de profil ne doit pas dépasser 2 Mo.")
            try:
                img = Image.open(self.photo)
                if img.format not in ['JPEG', 'PNG']:
                    raise ValidationError("La photo de profil doit être au format JPEG ou PNG.")
            except Exception:
                raise ValidationError("Fichier de photo invalide.")
        
        # Enforce service requirement for saisie_ec and saisie_er
        if self.role in ['saisie_ec', 'saisie_er'] and not self.service:
            raise ValidationError("Les rôles 'Responsable Service DR' et 'Responsable Service DP' doivent être associés à un service.")
        # Enforce no service for admin_saisie and admin_reponse
        if self.role in ['admin_saisie', 'admin_reponse'] and self.service:
            raise ValidationError("Les rôles 'Directeur Régional' et 'Directeur Provincial' ne doivent pas être associés à un service.")
        # Enforce destination requirement for saisie_ec, saisie_er, and admin_reponse
        if self.role in ['saisie_ec', 'saisie_er', 'admin_reponse'] and not self.destination:
            raise ValidationError("Les rôles 'Responsable Service DR', 'Responsable Service DP' et 'Directeur Provincial' doivent être associés à une destination.")
        # Ensure only one super_admin exists
        if self.role == 'super_admin' and UserProfile.objects.exclude(pk=self.pk).filter(role='super_admin').exists():
            raise ValidationError("Il ne peut y avoir qu'un seul Super Administrateur dans le système.")
        # Ensure only one admin_reponse per destination
        if self.role == 'admin_reponse' and self.destination and UserProfile.objects.exclude(pk=self.pk).filter(role='admin_reponse', destination=self.destination).exists():
            raise ValidationError(f"Un Directeur Provincial existe déjà pour la destination {self.destination.nom}.")
        # Ensure only one admin_saisie per destination
        if self.role == 'admin_saisie' and self.destination and UserProfile.objects.exclude(pk=self.pk).filter(role='admin_saisie', destination=self.destination).exists():
            raise ValidationError(f"Un Directeur Régional existe déjà pour la destination {self.destination.nom}.")

    class Meta:
        verbose_name = 'Profil utilisateur'
        verbose_name_plural = 'Profils utilisateurs'
        db_table = 'lettres_userprofile'


        