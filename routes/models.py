from django.db import models

class Route(models.Model):
    route_id = models.CharField(max_length=50, unique=True)
    route_short_name = models.CharField(max_length=50)
    route_long_name = models.CharField(max_length=255)
    route_type = models.IntegerField(default=3)  # 3 = bus
    city = models.CharField(max_length=100, default='Delhi')

    def __str__(self):
        return f"{self.route_short_name} - {self.route_long_name}"