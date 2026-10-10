package eco.roberts.familystalker.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import eco.roberts.familystalker.data.Account
import eco.roberts.familystalker.data.AccountRepository
import eco.roberts.familystalker.data.LocalFix
import eco.roberts.familystalker.data.LocationRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AppState(val account: Account? = null, val busy: Boolean = false, val message: String = "", val fix: LocalFix? = null)
class AppViewModel(private val accounts: AccountRepository, private val locations: LocationRepository) : ViewModel() {
    private val mutable = MutableStateFlow(AppState())
    val state = mutable.asStateFlow()
    private var operation: Job? = null

    private fun work(task: suspend () -> Unit) {
        if (mutable.value.busy) return
        mutable.update { it.copy(busy = true, message = "") }
        operation = viewModelScope.launch {
            try { task() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) { mutable.update { it.copy(message = failure.message ?: "Unable to complete this action.") } }
            finally { mutable.update { it.copy(busy = false) } }
        }
    }
    fun signIn(server: String, email: String, password: String) = work {
        val account = accounts.signIn(server, email, password)
        mutable.value = AppState(account = account, busy = true, message = "Signed in.")
    }
    fun locate() = work {
        check(mutable.value.account != null) { "Sign in first." }
        val fix = locations.current()
        mutable.update { it.copy(fix = fix, message = "Phone location displayed locally. Nothing was uploaded.") }
    }
    fun permissionDenied() { mutable.update { it.copy(message = "Location permission was denied. You can still view the map.") } }
    fun signOut() {
        operation?.cancel()
        mutable.value = AppState(busy = true)
        operation = viewModelScope.launch {
            try { accounts.signOut() }
            catch (failure: Exception) { mutable.update { it.copy(message = "Signed out locally. Server session could not be revoked; it will expire.") } }
            finally { mutable.update { it.copy(busy = false) } }
        }
    }
}
