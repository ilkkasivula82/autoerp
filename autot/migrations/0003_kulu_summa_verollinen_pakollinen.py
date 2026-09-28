from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("autot", "0002_kulu_summa_verollinen")]

    operations = [
        migrations.AlterField(
            model_name="kulu",
            name="summa_verollinen",
            field=models.BigIntegerField(help_text="senttiä", verbose_name="summa (sis. alv)"),
        ),
    ]
