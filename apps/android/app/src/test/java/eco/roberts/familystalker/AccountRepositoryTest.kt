package eco.roberts.familystalker

import eco.roberts.familystalker.data.ServerAccountRepository
import eco.roberts.familystalker.data.serverOrigin
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class AccountRepositoryTest {
    @Test fun rejectsUnsafeOrNonOriginAddresses() {
        for (url in listOf("http://localhost", "https://user:password@example.invalid", "https://example.invalid/path", "https://example.invalid?query=1", "https://example.invalid/#token")) {
            assertThrows(IllegalArgumentException::class.java) { serverOrigin(url) }
        }
        assertEquals("https://example.invalid:8443/", serverOrigin(" https://example.invalid:8443 ").toString())
    }

    private fun withServer(test: (MockWebServer, ServerAccountRepository) -> Unit) {
        val certificate = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val serverTls = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientTls = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        MockWebServer().use { server ->
            server.useHttps(serverTls.sslSocketFactory(), false)
            val client = OkHttpClient.Builder().sslSocketFactory(clientTls.sslSocketFactory(), clientTls.trustManager)
                .followRedirects(false).followSslRedirects(false).build()
            test(server, ServerAccountRepository(client))
        }
    }

    @Test fun nativeLoginAndLogoutUseSeparateAccountBearerWithoutUploadingLocations() = withServer { server, repository ->
        server.enqueue(MockResponse().setBody("{\"access_token\":\"synthetic-token\"}"))
        server.enqueue(MockResponse().setBody("{\"username\":\"Test member\",\"verified\":false}"))
        server.enqueue(MockResponse().setBody("{\"id\":\"synthetic-household\",\"revision\":0}"))
        server.enqueue(MockResponse().setBody("{\"signed_out\":true}"))
        runBlocking {
            val account = repository.signIn(server.url("/").toString(), " member@example.invalid ", "synthetic password")
            assertFalse(account.verified)
            assertEquals("Test member", account.name)
            repository.signOut()
        }
        val login = server.takeRequest()
        assertEquals("/api/login", login.path)
        assertEquals("native", login.getHeader("X-Stalker-Client"))
        assertNull(login.getHeader("Origin"))
        val payload = JSONObject(login.body.readUtf8())
        assertTrue(payload.getBoolean("native"))
        assertEquals("member@example.invalid", payload.getString("email"))
        for (path in listOf("/api/session", "/api/household", "/api/logout")) {
            val request = server.takeRequest()
            assertEquals(path, request.path)
            assertEquals("Bearer synthetic-token", request.getHeader("Authorization"))
        }
        assertEquals(4, server.requestCount)
    }

    @Test fun preservesRateLimitFeedback() = withServer { server, repository ->
        server.enqueue(MockResponse().setResponseCode(429).setBody("{\"detail\":\"Too many requests; try again later\"}"))
        val error = assertThrows(IOException::class.java) { runBlocking {
            repository.signIn(server.url("/").toString(), "member@example.invalid", "synthetic password")
        } }
        assertEquals("Too many requests; try again later", error.message)
        assertEquals(1, server.requestCount)
    }

    @Test fun doesNotFollowCredentialRedirects() = withServer { server, repository ->
        server.enqueue(MockResponse().setResponseCode(307).setHeader("Location", "/unexpected"))
        assertThrows(IOException::class.java) { runBlocking {
            repository.signIn(server.url("/").toString(), "member@example.invalid", "synthetic password")
        } }
        assertEquals(1, server.requestCount)
    }
}
