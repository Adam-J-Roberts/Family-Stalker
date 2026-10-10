package eco.roberts.familystalker.ui

import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import eco.roberts.familystalker.data.LocalFix
import eco.roberts.familystalker.BuildConfig
import okhttp3.Cache
import okhttp3.OkHttpClient
import org.maplibre.android.module.http.HttpRequestUtil
import java.io.File
import org.maplibre.android.MapLibre
import org.maplibre.android.annotations.MarkerOptions
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style

private const val OSM_STYLE = """{"version":8,"sources":{"osm":{"type":"raster","tiles":["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],"tileSize":256,"maxzoom":19,"attribution":"© OpenStreetMap contributors"}},"layers":[{"id":"osm","type":"raster","source":"osm"}]}"""
private var tileHttp: OkHttpClient? = null

@Suppress("DEPRECATION")
@Composable
fun MapSurface(fix: LocalFix?, modifier: Modifier = Modifier, onError: (String) -> Unit) {
    val context = LocalContext.current
    val latestFix by rememberUpdatedState(fix)
    val latestError by rememberUpdatedState(onError)
    val view = remember {
        MapLibre.getInstance(context)
        HttpRequestUtil.setLogEnabled(false)
        HttpRequestUtil.setOkHttpClient(tileHttp ?: OkHttpClient.Builder()
            .cache(Cache(File(context.cacheDir, "map-tiles"), 32L * 1024 * 1024))
            .addInterceptor { chain -> chain.proceed(chain.request().newBuilder()
                .header("User-Agent", "FamilyStalkerAndroid/${BuildConfig.VERSION_NAME} (+https://github.com/Adam-J-Roberts/Family-Stalker)")
                .build()) }.build().also { tileHttp = it })
        MapView(context).apply {
            onCreate(null)
            addOnDidFailLoadingMapListener { latestError("OpenStreetMap could not load. Check your connection and retry.") }
            getMapAsync { map -> map.setStyle(Style.Builder().fromJson(OSM_STYLE)) {
                latestFix?.let { point ->
                    map.addMarker(MarkerOptions().position(LatLng(point.latitude, point.longitude)).title("This phone"))
                    map.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(point.latitude, point.longitude), 15.0))
                }
            } }
        }
    }
    MapLifecycle(view, view::onStart, view::onResume, view::onPause, view::onStop, view::onDestroy)
    AndroidView(factory = { view }, modifier = modifier, update = { target ->
        target.getMapAsync { map ->
            if (map.style?.isFullyLoaded == true) {
                map.clear()
                latestFix?.let { point ->
                    val position = LatLng(point.latitude, point.longitude)
                    map.addMarker(MarkerOptions().position(position).title("This phone"))
                    map.moveCamera(CameraUpdateFactory.newLatLngZoom(position, 15.0))
                }
            }
        }
    })
}
