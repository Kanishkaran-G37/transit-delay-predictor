from django.db import models

class Stop(models.Model):
    stop_id = models.CharField(max_length=50, unique=True)
    stop_name = models.CharField(max_length=255)
    stop_lat = models.FloatField()
    stop_lon = models.FloatField()
    city = models.CharField(max_length=100, default='Delhi')

    def __str__(self):
        return self.stop_name

class RouteStop(models.Model):
    route = models.ForeignKey('routes.Route', on_delete=models.CASCADE)
    stop = models.ForeignKey(Stop, on_delete=models.CASCADE)
    stop_sequence = models.IntegerField()

    class Meta:
        unique_together = ('route', 'stop', 'stop_sequence')

    def __str__(self):
        return f"{self.route} → {self.stop}"