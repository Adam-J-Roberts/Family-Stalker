package eco.roberts.familystalker.ui

import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import android.os.Handler
import android.os.Looper
import com.google.android.gms.maps.CameraUpdateFactory
import com.google.android.gms.maps.MapView
import com.google.android.gms.maps.model.LatLng
import com.google.android.gms.maps.model.MarkerOptions
import eco.roberts.familystalker.data.LocalFix

@Composable
fun MapSurface(fix: LocalFix?, modifier: Modifier = Modifier, onError: (String) -> Unit) {
    val context = LocalContext.current
    val latestFix by rememberUpdatedState(fix)
    val latestError by rememberUpdatedState(onError)
    val view = remember { MapView(context).apply { onCreate(null) } }
    DisposableEffect(view) {
        val handler = Handler(Looper.getMainLooper())
        val timeout = Runnable { latestError("Google Maps did not finish loading. Check connection, API key restrictions and Google Play services.") }
        handler.postDelayed(timeout, 20_000)
        view.getMapAsync { map -> map.setOnMapLoadedCallback { handler.removeCallbacks(timeout) } }
        onDispose { handler.removeCallbacks(timeout) }
    }
    MapLifecycle(view, view::onStart, view::onResume, view::onPause, view::onStop, view::onDestroy)
    AndroidView(factory = { view }, modifier = modifier, update = { target -> target.getMapAsync { map ->
        map.uiSettings.isMapToolbarEnabled = false
        map.clear()
        latestFix?.let { point ->
            val position = LatLng(point.latitude, point.longitude)
            map.addMarker(MarkerOptions().position(position).title("This phone"))
            map.moveCamera(CameraUpdateFactory.newLatLngZoom(position, 15f))
        }
    } })
}
