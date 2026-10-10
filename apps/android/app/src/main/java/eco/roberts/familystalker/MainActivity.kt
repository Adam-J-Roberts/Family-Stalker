package eco.roberts.familystalker

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import eco.roberts.familystalker.data.PhoneLocationRepository
import eco.roberts.familystalker.data.ServerAccountRepository
import eco.roberts.familystalker.ui.AppViewModel
import eco.roberts.familystalker.ui.MapSurface

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val preferences = getSharedPreferences("server", MODE_PRIVATE)
        val factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T =
                AppViewModel(ServerAccountRepository(), PhoneLocationRepository(applicationContext)) as T
        }
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFA5F0BC), onPrimary = Color(0xFF10241A))) {
                val model: AppViewModel = viewModel(factory = factory)
                val state by model.state.collectAsStateWithLifecycle()
                var server by rememberSaveable { mutableStateOf(preferences.getString("url", BuildConfig.DEFAULT_SERVER_URL).orEmpty()) }
                var email by rememberSaveable { mutableStateOf("") }
                var password by remember { mutableStateOf("") }
                var showPassword by remember { mutableStateOf(false) }
                var mapTab by rememberSaveable { mutableStateOf(false) }
                var loadMap by remember { mutableStateOf(false) }
                var mapError by remember { mutableStateOf("") }
                val permissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
                    if (grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true || grants[Manifest.permission.ACCESS_FINE_LOCATION] == true) model.locate()
                    else model.permissionDenied()
                }
                LaunchedEffect(state.account) { password = ""; loadMap = false; mapTab = false; mapError = "" }
                BackHandler(enabled = mapTab) { mapTab = false; loadMap = false }
                Surface(Modifier.fillMaxSize()) {
                    Column(Modifier.safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Family-Stalker", style = MaterialTheme.typography.headlineLarge)
                        if (state.message.isNotBlank()) Text(state.message, color = MaterialTheme.colorScheme.primary)
                        if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                        val account = state.account
                        if (account == null) {
                            Text("Connect to your household", style = MaterialTheme.typography.titleLarge)
                            OutlinedTextField(server, { server = it }, label = { Text("HTTPS server URL") }, singleLine = true, enabled = !state.busy,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
                            OutlinedTextField(email, { email = it }, label = { Text("Email") }, singleLine = true, enabled = !state.busy,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), modifier = Modifier.fillMaxWidth())
                            OutlinedTextField(password, { password = it }, label = { Text("Password") }, singleLine = true, enabled = !state.busy,
                                visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                                trailingIcon = { TextButton(onClick = { showPassword = !showPassword }) { Text(if (showPassword) "Hide" else "Show") } },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth())
                            Button(onClick = { preferences.edit().putString("url", server.trim()).apply(); model.signIn(server, email, password) }, enabled = !state.busy) { Text("Sign in") }
                            Text("Use an account already invited to your server. Account sessions stay in memory; reopening the app requires sign-in.")
                        } else {
                            Text("Welcome, ${account.name}")
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                FilterChip(!mapTab, { mapTab = false; loadMap = false }, label = { Text("Setup") })
                                FilterChip(mapTab, { mapTab = true }, label = { Text("Map") })
                                TextButton(onClick = { model.signOut() }) { Text("Sign out") }
                            }
                            if (!mapTab) {
                                Text("Setup checklist", style = MaterialTheme.typography.titleLarge)
                                Text("✓ Connected and signed in")
                                Text(if (account.verified) "✓ Account email confirmed" else "○ Confirm your account email in the server website")
                                Text("○ Enroll and approve this Android device — next implementation milestone")
                                Text("○ Enable encrypted sharing — after device approval")
                                Text("You can test this phone’s map now. This build does not upload locations or display household records.")
                                Button(onClick = { mapTab = true }) { Text("Test map on this phone") }
                                OutlinedButton(onClick = { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(server))) }) { Text("Open server website") }
                            } else {
                                Text("Phone map preview", style = MaterialTheme.typography.titleLarge)
                                Text(if (BuildConfig.MAP_PROVIDER == "google") "Google Maps" else "OpenStreetMap · MapLibre")
                                Text("Loading a map sends the viewed region to the provider. Your phone location stays local to this app and map provider in this preview.")
                                if (!loadMap) Button(onClick = { loadMap = true; mapError = "" }) { Text("Load map") }
                                else {
                                    MapSurface(state.fix, Modifier.fillMaxWidth().height(360.dp)) { mapError = it }
                                    Button(onClick = { permissions.launch(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION)) }, enabled = !state.busy) { Text("Show my phone once") }
                                    if (BuildConfig.MAP_PROVIDER == "openstreetmap") Text("© OpenStreetMap contributors", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                if (mapError.isNotBlank()) {
                                    Text(mapError, color = MaterialTheme.colorScheme.error)
                                    OutlinedButton(onClick = { loadMap = false; mapError = "" }) { Text("Reload map") }
                                }
                                state.fix?.let { Text("Accuracy: ±${it.accuracy.toInt()} m. Location sharing is not enabled.") }
                            }
                        }
                    }
                }
            }
        }
    }
}
