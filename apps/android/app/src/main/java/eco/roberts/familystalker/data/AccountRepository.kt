package eco.roberts.familystalker.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

data class Account(val name: String, val verified: Boolean, val household: String)
interface AccountRepository {
    suspend fun signIn(server: String, email: String, password: String): Account
    suspend fun signOut()
}

fun serverOrigin(raw: String): HttpUrl {
    val url = raw.trim().toHttpUrlOrNull() ?: throw IllegalArgumentException("Enter your HTTPS server address.")
    require(url.isHttps && url.username.isEmpty() && url.password.isEmpty() &&
        url.encodedPath == "/" && url.query == null && url.fragment == null) {
        "Use an HTTPS server address without a path, credentials, query or fragment."
    }
    return url
}

class ServerAccountRepository(
    private val client: OkHttpClient = OkHttpClient.Builder()
        .followRedirects(false).followSslRedirects(false)
        .connectTimeout(15, TimeUnit.SECONDS).callTimeout(25, TimeUnit.SECONDS).build()
) : AccountRepository {
    private var server: HttpUrl? = null
    private var token: String? = null

    private suspend fun request(origin: HttpUrl, path: String, payload: JSONObject? = null, bearer: String? = null): JSONObject =
        withContext(Dispatchers.IO) {
            val builder = Request.Builder().url(origin.resolve(path)!!).header("X-Stalker-Client", "native")
            bearer?.let { builder.header("Authorization", "Bearer $it") }
            payload?.let { builder.post(it.toString().toRequestBody("application/json".toMediaType())) }
            client.newCall(builder.build()).execute().use { response ->
                val body = response.body?.string().orEmpty()
                val json = runCatching { JSONObject(body) }.getOrElse { JSONObject() }
                if (!response.isSuccessful) {
                    val detail = json.optString("detail").takeIf { it.isNotBlank() }
                    throw IOException(detail ?: "Server request failed (${response.code}).")
                }
                json
            }
        }

    override suspend fun signIn(server: String, email: String, password: String): Account {
        val origin = serverOrigin(server)
        require(email.trim().isNotEmpty() && password.isNotEmpty()) { "Enter your email and password." }
        val login = request(origin, "/api/login", JSONObject().put("email", email.trim()).put("password", password).put("native", true))
        val access = login.getString("access_token")
        try {
            val session = request(origin, "/api/session", bearer = access)
            val household = request(origin, "/api/household", bearer = access)
            this.server = origin
            token = access
            return Account(session.getString("username"), session.getBoolean("verified"), household.getString("id"))
        } catch (failure: Exception) {
            runCatching { request(origin, "/api/logout", JSONObject(), access) }
            throw failure
        }
    }

    override suspend fun signOut() {
        val origin = server
        val access = token
        server = null
        token = null
        if (origin != null && access != null) request(origin, "/api/logout", JSONObject(), access)
    }
}
