# Generated by Django 5.2.4 on 2025-07-25 14:52

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Destination",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "nom",
                    models.CharField(
                        choices=[
                            ("Oujda-Angad", "Oujda-Angad"),
                            ("Nador", "Nador"),
                            ("Driouch", "Driouch"),
                            ("Berkane", "Berkane"),
                            ("Taourirt", "Taourirt"),
                            ("Guercif", "Guercif"),
                            ("Figuig", "Figuig"),
                        ],
                        max_length=100,
                        unique=True,
                        verbose_name="Nom de la destination",
                    ),
                ),
                (
                    "telephone",
                    models.CharField(
                        blank=True, max_length=20, verbose_name="Numéro de téléphone"
                    ),
                ),
                (
                    "email",
                    models.EmailField(
                        blank=True,
                        max_length=254,
                        validators=[django.core.validators.EmailValidator()],
                        verbose_name="Adresse e-mail",
                    ),
                ),
            ],
            options={
                "verbose_name": "Destination",
                "verbose_name_plural": "Destinations",
                "ordering": ["nom"],
            },
        ),
        migrations.CreateModel(
            name="Lettre",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("subject", models.CharField(max_length=255, verbose_name="Sujet")),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("Financement", "Financement"),
                            ("Rapport", "Rapport"),
                            ("Formation", "Formation"),
                            ("Administrative", "Administrative"),
                            ("Technique", "Technique"),
                            ("Juridique", "Juridique"),
                        ],
                        max_length=50,
                        verbose_name="Catégorie",
                    ),
                ),
                ("date", models.DateField(verbose_name="Date de réception")),
                ("deadline", models.DateField(verbose_name="Date limite")),
                (
                    "sent_to_all_destinations",
                    models.BooleanField(
                        default=False, verbose_name="Envoyé à toutes les destinations"
                    ),
                ),
                (
                    "service",
                    models.CharField(
                        choices=[
                            ("SGP", "SGP"),
                            ("DRH", "DRH"),
                            ("INFRA", "INFRA"),
                            ("DP", "DP"),
                            ("MARITIME", "MARITIME"),
                        ],
                        max_length=20,
                        verbose_name="Service",
                    ),
                ),
                (
                    "format",
                    models.CharField(
                        choices=[
                            ("Excel", "Excel"),
                            ("PDF", "PDF"),
                            ("Word", "Word"),
                            ("Autre", "Autre"),
                        ],
                        max_length=20,
                        verbose_name="Format",
                    ),
                ),
                (
                    "priority",
                    models.CharField(
                        choices=[
                            ("low", "Faible"),
                            ("medium", "Moyenne"),
                            ("high", "Élevée"),
                        ],
                        default="medium",
                        max_length=20,
                        verbose_name="Priorité",
                    ),
                ),
                (
                    "description",
                    models.TextField(blank=True, verbose_name="Description"),
                ),
                (
                    "image_file",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to="lettres/images/",
                        verbose_name="Image",
                    ),
                ),
                (
                    "response_template",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to="lettres/templates/",
                        verbose_name="Template de réponse",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Créé le"),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("en_attente", "En attente"),
                            ("repondu", "Répondu"),
                            ("en_retard", "En retard"),
                        ],
                        default="en_attente",
                        max_length=20,
                        verbose_name="Statut",
                    ),
                ),
                (
                    "rappels_envoyes",
                    models.IntegerField(default=0, verbose_name="Rappels envoyés"),
                ),
                (
                    "date_dernier_rappel",
                    models.DateField(
                        blank=True, null=True, verbose_name="Date du dernier rappel"
                    ),
                ),
                (
                    "destinations",
                    models.ManyToManyField(
                        blank=True,
                        to="lettres.destination",
                        verbose_name="Destinations",
                    ),
                ),
            ],
            options={
                "verbose_name": "Lettre",
                "verbose_name_plural": "Lettres",
                "ordering": ["-date"],
            },
        ),
        migrations.CreateModel(
            name="Response",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("en_attente", "En attente"),
                            ("repondu", "Répondu"),
                            ("en_retard", "En retard"),
                        ],
                        default="en_attente",
                        max_length=20,
                        verbose_name="Statut",
                    ),
                ),
                (
                    "date_reponse",
                    models.DateField(
                        blank=True, null=True, verbose_name="Date de réponse"
                    ),
                ),
                (
                    "temps_reponse",
                    models.IntegerField(
                        blank=True, null=True, verbose_name="Temps de réponse (heures)"
                    ),
                ),
                (
                    "commentaires",
                    models.TextField(
                        blank=True, null=True, verbose_name="Commentaires"
                    ),
                ),
                (
                    "response_file",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to="responses/files/",
                        verbose_name="Fichier de réponse",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Créé le"),
                ),
                (
                    "destination",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="lettres.destination",
                        verbose_name="Destination",
                    ),
                ),
                (
                    "lettre",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reponses",
                        to="lettres.lettre",
                        verbose_name="Lettre",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "Réponse régionale",
                "verbose_name_plural": "Réponses régionales",
                "ordering": ["destination__nom", "created_at"],
                "unique_together": {("lettre", "destination", "user")},
            },
        ),
        migrations.CreateModel(
            name="Rappel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[("email", "Email")], max_length=10, verbose_name="Type"
                    ),
                ),
                ("date", models.DateField(verbose_name="Date")),
                ("time", models.TimeField(verbose_name="Heure")),
                ("message", models.TextField(verbose_name="Message")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("sent", "Sent"),
                            ("delivered", "Delivered"),
                            ("failed", "Failed"),
                        ],
                        default="sent",
                        max_length=10,
                        verbose_name="Statut",
                    ),
                ),
                (
                    "response",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rappels",
                        to="lettres.response",
                        verbose_name="Réponse",
                    ),
                ),
            ],
            options={
                "verbose_name": "Rappel",
                "verbose_name_plural": "Rappels",
            },
        ),
        migrations.CreateModel(
            name="SystemSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "email_notifications",
                    models.BooleanField(
                        default=True, verbose_name="Notifications par email"
                    ),
                ),
                (
                    "reminder_frequency",
                    models.IntegerField(
                        choices=[
                            (24, "24 heures"),
                            (48, "48 heures"),
                            (72, "72 heures"),
                        ],
                        default=24,
                        verbose_name="Fréquence des rappels (heures)",
                    ),
                ),
                (
                    "escalation_time",
                    models.IntegerField(
                        choices=[
                            (48, "48 heures"),
                            (72, "72 heures"),
                            (96, "96 heures"),
                        ],
                        default=72,
                        verbose_name="Escalade après (heures)",
                    ),
                ),
                (
                    "archive_in_progress_after_year",
                    models.BooleanField(
                        default=True,
                        verbose_name="Archiver les requêtes en cours après 1 an",
                    ),
                ),
                (
                    "archive_closed_after_month",
                    models.BooleanField(
                        default=True,
                        verbose_name="Archiver les requêtes clôturées après 1 mois",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "Paramètres du système",
                "verbose_name_plural": "Paramètres du système",
            },
        ),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("super_admin", "Super Administrateur"),
                            ("admin_saisie", "Directeur Régional"),
                            ("saisie_ec", "Responsable Service DR"),
                            ("admin_reponse", "Directeur Provincial"),
                            ("saisie_er", "Responsable Service DP"),
                        ],
                        max_length=20,
                        verbose_name="Rôle",
                    ),
                ),
                (
                    "service",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("SGP", "SGP"),
                            ("DRH", "DRH"),
                            ("INFRA", "INFRA"),
                            ("DP", "DP"),
                            ("MARITIME", "MARITIME"),
                        ],
                        max_length=20,
                        null=True,
                        verbose_name="Service",
                    ),
                ),
                (
                    "destination",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="lettres.destination",
                        verbose_name="Destination",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "Profil utilisateur",
                "verbose_name_plural": "Profils utilisateurs",
                "db_table": "lettres_userprofile",
            },
        ),
    ]
