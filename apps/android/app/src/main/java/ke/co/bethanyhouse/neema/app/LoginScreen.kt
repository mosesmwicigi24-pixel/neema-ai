package ke.co.bethanyhouse.neema.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.outlined.Forum
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.NeemaApplication
import ke.co.bethanyhouse.neema.core.auth.AuthException
import kotlinx.coroutines.launch

private val Night = Color(0xFF070D1C)
private val Moss = Color(0xFF589B31)

/** apps/web/src/app/login/page.tsx */
@Composable
fun LoginScreen(prefillEmail: String? = null, onSignedIn: () -> Unit) {
    val container = NeemaApplication.instance.container
    var email by remember { mutableStateOf(prefillEmail ?: container.sessionStore.lastEmail ?: "") }
    var password by remember { mutableStateOf("") }
    var show by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val focus = LocalFocusManager.current

    fun submit() {
        if (email.isBlank() || password.isBlank()) { error = "Please enter your email and password."; return }
        focus.clearFocus()
        loading = true; error = ""
        scope.launch {
            runCatching { container.auth.login(email.trim(), password) }
                .onSuccess { onSignedIn() }
                .onFailure { e ->
                    error = if (e is AuthException) e.message ?: "" else "Something went wrong. Please try again."
                }
            loading = false
        }
    }

    Box(
        Modifier.fillMaxSize()
            .background(Brush.verticalGradient(listOf(Color(0xFF0E2A18), Night, Night)))
            .systemBarsPadding().imePadding(),
    ) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(Moss), contentAlignment = Alignment.Center) {
                    Icon(Icons.Outlined.Forum, null, tint = Color.White)
                }
                Spacer(Modifier.width(10.dp))
                Text("Neema", color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.ExtraBold)
            }
            Spacer(Modifier.height(28.dp))
            Text("Manage conversations,\norders & customers", color = Color.White, fontSize = 26.sp, fontWeight = FontWeight.Bold, lineHeight = 32.sp)
            Spacer(Modifier.height(10.dp))
            listOf("💬  Live conversation monitoring", "📦  Order & catalog management", "📊  Customer insights & CRM").forEach {
                Text(it, color = Color(0xFFB5DA8B), fontSize = 14.sp, modifier = Modifier.padding(vertical = 2.dp))
            }
            Spacer(Modifier.height(32.dp))

            Surface(shape = RoundedCornerShape(20.dp), color = Color(0xFF0A1229), tonalElevation = 0.dp) {
                Column(Modifier.padding(20.dp)) {
                    Text("Sign in", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                    Text("Enter your credentials to access the dashboard", color = Color(0xFF8AA89A), fontSize = 13.sp)
                    Spacer(Modifier.height(18.dp))
                    val fieldColors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = Color.White, unfocusedTextColor = Color.White,
                        focusedBorderColor = Moss, unfocusedBorderColor = Color(0xFF1F367A),
                        focusedLabelColor = Color(0xFF9CCD65), unfocusedLabelColor = Color(0xFF8AA89A),
                        cursorColor = Moss,
                    )
                    OutlinedTextField(
                        value = email, onValueChange = { email = it }, label = { Text("Email address") },
                        singleLine = true, colors = fieldColors, modifier = Modifier.fillMaxWidth(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                    )
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = password, onValueChange = { password = it }, label = { Text("Password") },
                        singleLine = true, colors = fieldColors, modifier = Modifier.fillMaxWidth(),
                        visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
                        trailingIcon = {
                            IconButton(onClick = { show = !show }) {
                                Icon(if (show) Icons.Default.VisibilityOff else Icons.Default.Visibility, "Show password", tint = Color(0xFF8AA89A))
                            }
                        },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { submit() }),
                    )
                    if (error.isNotEmpty()) {
                        Spacer(Modifier.height(10.dp))
                        Text(error, color = Color(0xFFFCA5A5), fontSize = 12.sp)
                    }
                    Spacer(Modifier.height(18.dp))
                    Button(
                        onClick = ::submit, enabled = !loading,
                        colors = ButtonDefaults.buttonColors(containerColor = Moss, contentColor = Color.White),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth().height(50.dp),
                    ) {
                        if (loading) CircularProgressIndicator(Modifier.size(20.dp), color = Color.White, strokeWidth = 2.dp)
                        else Text("Sign in", fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(14.dp))
                    Text("Contact your administrator if you need access.", color = Color(0xFF8AA89A), fontSize = 12.sp)
                }
            }
        }
    }
}

/**
 * components/ui/SessionExpiredModal.tsx: re-authenticate over the live
 * dashboard instead of throwing the agent back to the login page.
 */
@Composable
fun SessionExpiredDialog(email: String, onSuccess: () -> Unit, onSignOut: () -> Unit) {
    val container = NeemaApplication.instance.container
    var password by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    AlertDialog(
        onDismissRequest = {},
        title = { Text("Session expired") },
        text = {
            Column {
                Text("Your session timed out. Enter your password to continue where you left off.", fontSize = 14.sp)
                Spacer(Modifier.height(12.dp))
                Text(email, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = password, onValueChange = { password = it }, label = { Text("Password") },
                    singleLine = true, visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth(),
                )
                if (error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error, fontSize = 12.sp)
            }
        },
        confirmButton = {
            TextButton(enabled = !loading && password.isNotBlank(), onClick = {
                loading = true; error = ""
                scope.launch {
                    runCatching { container.auth.login(email, password) }
                        .onSuccess { onSuccess() }
                        .onFailure { error = (it as? AuthException)?.message ?: "Couldn't sign in — try again." }
                    loading = false
                }
            }) { Text(if (loading) "Signing in…" else "Continue") }
        },
        dismissButton = { TextButton(onClick = onSignOut) { Text("Sign out") } },
    )
}
