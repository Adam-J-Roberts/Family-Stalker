package eco.roberts.familystalker.data

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

data class LocalFix(val latitude: Double, val longitude: Double, val accuracy: Float)
interface LocationRepository { suspend fun current(): LocalFix }

class PhoneLocationRepository(context: Context) : LocationRepository {
    private val manager = context.getSystemService(LocationManager::class.java)
    @SuppressLint("MissingPermission") // UI requests coarse+fine together before calling this repository.
    @Suppress("DEPRECATION")
    override suspend fun current(): LocalFix = withTimeout(20_000) {
        suspendCancellableCoroutine { continuation ->
            val listener = object : LocationListener {
                override fun onLocationChanged(location: Location) {
                    manager.removeUpdates(this)
                    if (continuation.isActive) continuation.resume(LocalFix(location.latitude, location.longitude, location.accuracy))
                }
                override fun onProviderDisabled(provider: String) {
                    manager.removeUpdates(this)
                    if (continuation.isActive) continuation.resumeWithException(IllegalStateException("Turn on phone location services and try again."))
                }
                override fun onProviderEnabled(provider: String) {}
                override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
            }
            continuation.invokeOnCancellation { manager.removeUpdates(listener) }
            try {
                val fine = contextPermission(managerContext = context)
                val provider = if (fine && manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) LocationManager.GPS_PROVIDER
                    else LocationManager.NETWORK_PROVIDER
                if (!manager.isProviderEnabled(provider)) throw IllegalStateException("Turn on phone location services and try again.")
                manager.requestSingleUpdate(provider, listener, Looper.getMainLooper())
            } catch (failure: Exception) {
                if (continuation.isActive) continuation.resumeWithException(failure)
            }
        }
    }

    private val context = context.applicationContext
    private fun contextPermission(managerContext: Context) = managerContext.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == android.content.pm.PackageManager.PERMISSION_GRANTED
}
