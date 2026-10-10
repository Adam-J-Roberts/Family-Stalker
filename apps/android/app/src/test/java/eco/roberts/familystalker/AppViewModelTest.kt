package eco.roberts.familystalker

import eco.roberts.familystalker.data.*
import eco.roberts.familystalker.ui.AppViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.*
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AppViewModelTest {
    @Test fun pendingEmailAndLocalFixRemainSeparateFromSharing() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            var signedOut = false
            val accounts = object : AccountRepository {
                override suspend fun signIn(server: String, email: String, password: String) = Account("Synthetic", false, "test")
                override suspend fun signOut() { signedOut = true }
            }
            val locations = object : LocationRepository { override suspend fun current() = LocalFix(1.0, 2.0, 30f) }
            val model = AppViewModel(accounts, locations)
            model.signIn("https://example.invalid", "test@example.invalid", "synthetic")
            advanceUntilIdle()
            assertFalse(model.state.value.account!!.verified)
            model.locate()
            advanceUntilIdle()
            assertEquals(1.0, model.state.value.fix!!.latitude, 0.0)
            model.signOut()
            advanceUntilIdle()
            assertTrue(signedOut)
            assertNull(model.state.value.fix)
            assertNull(model.state.value.account)
        } finally { Dispatchers.resetMain() }
    }
    @Test fun locationRequiresSignInAndDeniedPermissionHasFeedback() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            var called = false
            val accounts = object : AccountRepository {
                override suspend fun signIn(server: String, email: String, password: String) = error("Unused")
                override suspend fun signOut() {}
            }
            val locations = object : LocationRepository { override suspend fun current(): LocalFix { called = true; error("Unused") } }
            val model = AppViewModel(accounts, locations)
            model.locate()
            advanceUntilIdle()
            assertFalse(called)
            assertEquals("Sign in first.", model.state.value.message)
            model.permissionDenied()
            assertTrue(model.state.value.message.contains("permission was denied"))
        } finally { Dispatchers.resetMain() }
    }
}
