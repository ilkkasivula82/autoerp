from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("autot", "0004_sopimukset")]

    operations = [
        migrations.AddField(
            model_name="kuva",
            name="paikka",
            field=models.CharField(
                blank=True,
                choices=[
                    ("etu_vasen", "Edestä vasemmalta"),
                    ("edesta", "Suoraan edestä"),
                    ("etu_oikea", "Edestä oikealta"),
                    ("oikea_kylki", "Oikea kylki"),
                    ("taka_oikea", "Takaa oikealta"),
                    ("takaa", "Suoraan takaa"),
                    ("taka_vasen", "Takaa vasemmalta"),
                    ("vasen_kylki", "Vasen kylki"),
                    ("vanne", "Vanne ja rengas"),
                    ("kojelauta", "Kojelauta"),
                    ("mittaristo", "Mittaristo (km-lukema)"),
                    ("etuistuimet", "Etuistuimet"),
                    ("takaistuimet", "Takaistuimet"),
                    ("tavaratila", "Tavaratila"),
                    ("moottoritila", "Moottoritila"),
                ],
                max_length=20,
                verbose_name="vakiopaikka",
            ),
        ),
        migrations.AddConstraint(
            model_name="kuva",
            constraint=models.UniqueConstraint(
                condition=models.Q(("paikka", ""), _negated=True),
                fields=("kierto", "paikka"),
                name="kuva_vakiopaikka_uniikki",
            ),
        ),
    ]
