package ke.co.bethanyhouse.neema.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import ke.co.bethanyhouse.neema.NeemaApplication
import ke.co.bethanyhouse.neema.core.auth.AuthException
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons
import ke.co.bethanyhouse.neema.core.ui.theme.LightNeema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import kotlinx.coroutines.launch
import java.time.Year

// login/page.tsx palette — always the night theme, whatever the dashboard's.
private val Night = Palette.Prussian950
private val Panel = Palette.Prussian900
private val Line = Palette.Prussian800
private val Moss = Palette.Moss600
private val Willow = Palette.Willow600
private val Parchment = Palette.Willow50
private val Sprout = Palette.Willow400

/** apps/web/src/app/login/page.tsx */
@Composable
fun LoginScreen(prefillEmail: String? = null, onSignedIn: () -> Unit) {
    val container = NeemaApplication.instance.container
    LoginContent(
        initialEmail = prefillEmail ?: container.sessionStore.lastEmail ?: "",
        login = { e, p -> container.auth.login(e, p) },
        onSignedIn = onSignedIn,
    )
}

/**
 * The sign-in page. Phones get the web's mobile layout (small logo, form,
 * footer note); a wide screen adds the web's branding panel on the left.
 */
@Composable
internal fun LoginContent(
    initialEmail: String,
    login: suspend (String, String) -> Unit,
    onSignedIn: () -> Unit,
    initialPassword: String = "",
    initialError: String = "",
    initialLoading: Boolean = false,
    /** The footer year (tests pin it). */
    year: Int = Year.now().value,
) {
    var email by remember { mutableStateOf(initialEmail) }
    var password by remember { mutableStateOf(initialPassword) }
    var show by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(initialLoading) }
    var error by remember { mutableStateOf(initialError) }
    val scope = rememberCoroutineScope()
    val focus = LocalFocusManager.current

    fun submit() {
        if (loading) return
        if (email.isBlank() || password.isEmpty()) { error = "Please enter your email and password."; return }
        focus.clearFocus()
        loading = true; error = ""
        scope.launch {
            runCatching { login(email.trim(), password) }
                .onSuccess { onSignedIn() }
                .onFailure { e ->
                    error = if (e is AuthException) e.message ?: "Invalid email or password. Please try again."
                    else "Something went wrong. Please try again."
                }
            loading = false
        }
    }

    BoxWithConstraints(Modifier.fillMaxSize().background(Night)) {
        // Tailwind's lg (1024) shows the branding panel; xl (1280) widens it.
        val wide = maxWidth >= 1024.dp
        val panelWidth = if (maxWidth >= 1280.dp) 480.dp else 420.dp
        Row(Modifier.fillMaxSize()) {
            if (wide) BrandPanel(Modifier.width(panelWidth).fillMaxHeight(), year)
            Box(
                Modifier.weight(1f).fillMaxHeight().safeDrawingPadding()
                    .verticalScroll(rememberScrollState()).padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                Column(Modifier.widthIn(max = 384.dp).fillMaxWidth()) {
                    if (!wide) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            MossLogo(36.dp, iconSize = 20.dp)
                            Column(Modifier.padding(start = 10.dp)) {
                                Text("Neema", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                                Text("ADMIN", color = Willow, fontSize = 10.sp, letterSpacing = 1.sp, modifier = Modifier.padding(top = 2.dp))
                            }
                        }
                        Spacer(Modifier.height(32.dp))
                    }
                    Text("Sign in", color = Parchment, fontSize = 24.sp, lineHeight = 32.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.6).sp, modifier = Modifier.semantics { heading() })
                    Spacer(Modifier.height(4.dp))
                    Text("Enter your credentials to access the dashboard", color = Willow, fontSize = 14.sp, lineHeight = 20.sp)
                    Spacer(Modifier.height(32.dp))

                    FieldLabel("Email address")
                    NightField(
                        label = "Email address",
                        value = email, onChange = { email = it; error = "" }, placeholder = "admin@bethanyhouse.com",
                        keyboard = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                    )
                    Spacer(Modifier.height(16.dp))
                    FieldLabel("Password")
                    NightField(
                        label = "Password",
                        value = password, onChange = { password = it; error = "" }, placeholder = "••••••••",
                        // This input has no placeholder colour class: the browser's half-strength text colour.
                        placeholderColor = Parchment.copy(alpha = 0.5f),
                        keyboard = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                        actions = KeyboardActions(onDone = { submit() }),
                        visual = if (show) VisualTransformation.None else PasswordVisualTransformation(),
                        trailing = {
                            Box(
                                Modifier.size(48.dp).clip(CircleShape).clickable(role = Role.Button) { show = !show },
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    if (show) WebIcons.EyeOff else WebIcons.Eye,
                                    if (show) "Hide password" else "Show password",
                                    tint = Willow, modifier = Modifier.size(16.dp),
                                )
                            }
                        },
                    )

                    if (error.isNotEmpty()) {
                        Spacer(Modifier.height(16.dp))
                        Row(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                                .background(LightNeema.red.copy(alpha = 0.15f))
                                .border(1.dp, Palette.Red800.copy(alpha = 0.6f), RoundedCornerShape(8.dp))
                                .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite }
                                .padding(12.dp),
                        ) {
                            Icon(WebIcons.AlertCircle, null, tint = Palette.Red400, modifier = Modifier.padding(top = 2.dp).size(16.dp))
                            Spacer(Modifier.width(10.dp))
                            Text(error, color = Palette.Red300, fontSize = 12.sp, lineHeight = 16.sp)
                        }
                    }

                    Spacer(Modifier.height(24.dp))
                    Row(
                        Modifier.fillMaxWidth().heightIn(min = 48.dp)
                            .alpha(if (loading) 0.6f else 1f)
                            .shadow(if (loading) 0.dp else 10.dp, RoundedCornerShape(12.dp), ambientColor = Moss, spotColor = Moss)
                            .clip(RoundedCornerShape(12.dp))
                            .background(Moss)
                            .clickable(enabled = !loading, role = Role.Button) { submit() }
                            .padding(vertical = 8.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (loading) {
                            CircularProgressIndicator(Modifier.size(16.dp), color = Color.White, strokeWidth = 2.dp, trackColor = Color.White.copy(alpha = 0.4f))
                            Spacer(Modifier.width(8.dp))
                            Text("Signing in…", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                        } else {
                            Text("Sign in", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                        }
                    }

                    Spacer(Modifier.height(32.dp))
                    Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
                    Spacer(Modifier.height(24.dp))
                    // willow-600: the web's moss-700 is 3.5:1 on the night background.
                    Text(
                        "Access restricted to Bethany House staff.\nContact your administrator if you need access.",
                        color = Willow, fontSize = 12.sp, lineHeight = 16.sp, textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
    }
}

/** The web's `focus:ring` — a soft 3dp halo drawn outside the field, not taking layout space. */
private fun Modifier.focusRing(focused: Boolean, color: Color): Modifier = if (!focused) this else drawBehind {
    val w = 3.dp.toPx()
    drawRoundRect(
        color, topLeft = Offset(-w, -w), size = androidx.compose.ui.geometry.Size(size.width + 2 * w, size.height + 2 * w),
        cornerRadius = androidx.compose.ui.geometry.CornerRadius(15.dp.toPx()),
    )
}

/** The left branding panel shown on wide screens (lg:flex on the web). */
@Composable
private fun BrandPanel(modifier: Modifier, year: Int) {
    Box(
        modifier.background(Panel)
            .drawBehind {
                // Radial moss glow from the top-left, then the right-hand border.
                drawRect(
                    Brush.radialGradient(
                        listOf(Moss.copy(alpha = 0.15f), Color.Transparent),
                        center = Offset.Zero, radius = size.maxDimension * 0.75f,
                    ),
                )
                drawRect(Line, topLeft = Offset(size.width - 1.dp.toPx(), 0f), size = androidx.compose.ui.geometry.Size(1.dp.toPx(), size.height))
            }
            .systemBarsPadding()
            .padding(40.dp),
    ) {
        Row(Modifier.align(Alignment.TopStart), verticalAlignment = Alignment.CenterVertically) {
            MossLogo(40.dp, iconSize = 24.dp, glow = true)
            Column(Modifier.padding(start = 12.dp)) {
                Text("Neema", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold, lineHeight = 18.sp, letterSpacing = (-0.45).sp)
                Text(
                    "BETHANY HOUSE · ADMIN", color = Willow, fontSize = 10.sp, fontWeight = FontWeight.Medium,
                    letterSpacing = 1.sp, modifier = Modifier.padding(top = 2.dp),
                )
            }
        }
        Column(Modifier.align(Alignment.CenterStart)) {
            Text("Manage conversations,", color = Parchment, fontSize = 24.sp, fontWeight = FontWeight.Bold, lineHeight = 33.sp)
            Text("grow your business.", color = Sprout, fontSize = 24.sp, fontWeight = FontWeight.Bold, lineHeight = 33.sp)
            Spacer(Modifier.height(8.dp))
            Text(
                "AI-powered WhatsApp assistant for Bethany House — handling orders, queries, and sales around the clock.",
                color = Willow, fontSize = 14.sp, lineHeight = 23.sp,
            )
        }
        Text(
            "© $year Bethany House · Nairobi, Kenya", color = Willow, fontSize = 12.sp, lineHeight = 16.sp,
            modifier = Modifier.align(Alignment.BottomStart),
        )
    }
}

/**
 * The moss chat-bubble mark of the login page: the branding panel's glows
 * moss; the phone one carries a plain shadow-lg.
 */
@Composable
private fun MossLogo(size: Dp, iconSize: Dp, glow: Boolean = false) {
    Box(
        Modifier.size(size)
            .then(
                if (glow) Modifier.shadow(12.dp, RoundedCornerShape(12.dp), ambientColor = Moss, spotColor = Moss)
                else Modifier.shadow(6.dp, RoundedCornerShape(12.dp)),
            )
            .clip(RoundedCornerShape(12.dp)).background(Moss),
        contentAlignment = Alignment.Center,
    ) { Icon(WebIcons.Logo, null, tint = Color.White, modifier = Modifier.size(iconSize)) }
}

@Composable
private fun FieldLabel(text: String) {
    Text(
        text.uppercase(), color = Willow, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp,
        modifier = Modifier.padding(bottom = 8.dp),
    )
}

/** The web's 44dp night input: moss border and a soft ring on focus. */
@Composable
private fun NightField(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    placeholder: String,
    keyboard: KeyboardOptions,
    actions: KeyboardActions = KeyboardActions.Default,
    visual: VisualTransformation = VisualTransformation.None,
    trailing: (@Composable () -> Unit)? = null,
    placeholderColor: Color = Willow,
) {
    val source = remember { MutableInteractionSource() }
    val focused by source.collectIsFocusedAsState()
    BasicTextField(
        value = value, onValueChange = onChange, singleLine = true,
        textStyle = TextStyle(color = Parchment, fontSize = 14.sp),
        cursorBrush = SolidColor(Moss), keyboardOptions = keyboard, keyboardActions = actions,
        visualTransformation = visual, interactionSource = source,
        modifier = Modifier.fillMaxWidth().semantics { contentDescription = label },
        decorationBox = { inner ->
            Row(
                Modifier.fillMaxWidth().heightIn(min = 48.dp)
                    .focusRing(focused, Moss.copy(alpha = 0.2f))
                    .clip(RoundedCornerShape(12.dp)).background(Panel)
                    .border(1.dp, if (focused) Moss else Line, RoundedCornerShape(12.dp))
                    .padding(start = 16.dp, end = if (trailing != null) 2.dp else 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.weight(1f)) {
                    if (value.isEmpty()) Text(placeholder, color = placeholderColor, fontSize = 14.sp)
                    inner()
                }
                trailing?.invoke()
            }
        },
    )
}

// ── Session expired (components/ui/SessionExpiredModal.tsx) ────────────────

/**
 * Re-authenticate over the live dashboard instead of throwing the agent back
 * to the login page. Not dismissable: Continue or Sign out.
 */
@Composable
fun SessionExpiredDialog(email: String, onSuccess: () -> Unit, onSignOut: () -> Unit) {
    val container = NeemaApplication.instance.container
    Dialog(
        onDismissRequest = {},
        properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false, usePlatformDefaultWidth = false),
    ) {
        SessionExpiredCard(email, login = { e, p -> container.auth.login(e, p) }, onSuccess = onSuccess, onSignOut = onSignOut)
    }
}

/** The modal's card; its own composable so it renders in screenshot tests. */
@Composable
internal fun SessionExpiredCard(
    email: String,
    login: suspend (String, String) -> Unit,
    onSuccess: () -> Unit,
    onSignOut: () -> Unit,
    initialPassword: String = "",
    initialError: String = "",
    initialLoading: Boolean = false,
    autoFocus: Boolean = true,
) {
    var password by remember { mutableStateOf(initialPassword) }
    var loading by remember { mutableStateOf(initialLoading) }
    var error by remember { mutableStateOf(initialError) }
    val scope = rememberCoroutineScope()
    val focus = remember { FocusRequester() }
    if (autoFocus) LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }

    fun submit() {
        if (password.isEmpty() || loading) return
        loading = true; error = ""
        scope.launch {
            runCatching { login(email, password) }
                .onSuccess { onSuccess() }
                .onFailure {
                    error = if (it is AuthException && it.message?.startsWith("Invalid") != false) "Incorrect password. Please try again."
                    else if (it is AuthException) it.message!!
                    else "Something went wrong. Please try again."
                    loading = false
                }
        }
    }

    val stone900 = Palette.Stone900
    val stone500 = Palette.Stone500
    val stone200 = Palette.Stone200
    Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.4f)).safeDrawingPadding(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.padding(horizontal = 16.dp, vertical = 24.dp).widthIn(max = 384.dp).fillMaxWidth()
                .shadow(24.dp, RoundedCornerShape(16.dp)).clip(RoundedCornerShape(16.dp)).background(Color.White),
        ) {
            Box(Modifier.fillMaxWidth().height(4.dp).background(Brush.horizontalGradient(listOf(Palette.Green600, Palette.Emerald400))))
            // 32dp inside the card on a phone (the web's p-8); 24dp on a 360dp screen.
            Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = if (LocalConfiguration.current.screenWidthDp < 380) 24.dp else 32.dp, vertical = 32.dp)) {
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Box(
                        Modifier.size(56.dp).clip(CircleShape).background(Palette.Amber50).border(1.dp, Palette.Amber200, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) { Icon(WebIcons.Warning, null, tint = Palette.Amber500, modifier = Modifier.size(28.dp)) }
                }
                Spacer(Modifier.height(20.dp))
                Text("Session expired", color = stone900, fontSize = 20.sp, lineHeight = 28.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().semantics { heading() })
                Spacer(Modifier.height(4.dp))
                Text(
                    "Please enter your password to continue where you left off.", color = stone500, fontSize = 14.sp,
                    lineHeight = 20.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(24.dp))

                Text("Signed in as", color = stone500, fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(6.dp))
                Text(
                    email, color = Palette.Stone600, fontSize = 14.sp, lineHeight = 20.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Palette.Stone100)
                        .border(1.dp, stone200, RoundedCornerShape(12.dp)).padding(horizontal = 14.dp, vertical = 10.dp),
                )
                Spacer(Modifier.height(16.dp))
                Text("Password", color = stone500, fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(6.dp))
                val source = remember { MutableInteractionSource() }
                val focused by source.collectIsFocusedAsState()
                BasicTextField(
                    value = password, onValueChange = { password = it }, singleLine = true,
                    textStyle = TextStyle(color = stone900, fontSize = 14.sp, lineHeight = 20.sp), cursorBrush = SolidColor(Palette.Green500),
                    visualTransformation = PasswordVisualTransformation(), interactionSource = source,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { submit() }),
                    modifier = Modifier.fillMaxWidth().focusRequester(focus).semantics { contentDescription = "Password" },
                    decorationBox = { inner ->
                        Box(
                            Modifier.fillMaxWidth().heightIn(min = 48.dp)
                                .focusRing(focused, Palette.Green500.copy(alpha = 0.4f))
                                .clip(RoundedCornerShape(12.dp)).background(Color.White)
                                .border(1.dp, if (focused) Palette.Green500 else stone200, RoundedCornerShape(12.dp))
                                .padding(horizontal = 14.dp, vertical = 10.dp),
                            contentAlignment = Alignment.CenterStart,
                        ) {
                            if (password.isEmpty()) Text("••••••••", color = Palette.Stone400, fontSize = 14.sp, lineHeight = 20.sp)
                            inner()
                        }
                    },
                )

                if (error.isNotEmpty()) {
                    Spacer(Modifier.height(16.dp))
                    Text(
                        error, color = Palette.Red600, fontSize = 14.sp, lineHeight = 20.sp,
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(Palette.Red50)
                            .border(1.dp, Palette.Red100, RoundedCornerShape(8.dp))
                            .semantics { liveRegion = LiveRegionMode.Polite }
                            .padding(horizontal = 14.dp, vertical = 10.dp),
                    )
                }

                Spacer(Modifier.height(16.dp))
                val enabled = !loading && password.isNotEmpty()
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 48.dp).alpha(if (enabled) 1f else 0.6f)
                        .clip(RoundedCornerShape(12.dp)).background(stone900).clickable(enabled = enabled, role = Role.Button) { submit() }
                        .padding(vertical = 8.dp),
                    horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (loading) {
                        CircularProgressIndicator(Modifier.size(16.dp), color = Color.White.copy(alpha = 0.75f), strokeWidth = 2.dp, trackColor = Color.White.copy(alpha = 0.25f))
                        Spacer(Modifier.width(8.dp))
                        Text("Signing in…", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    } else Text("Continue", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                }
                // space-y-4 (Tailwind v4 margin-bottom) spaces the two buttons 16dp apart too.
                Spacer(Modifier.height(12.dp))
                // stone-500: the web's stone-400 is 2.5:1 on white.
                Text(
                    "Sign out", color = stone500, fontSize = 14.sp, lineHeight = 20.sp, textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onSignOut)
                        .heightIn(min = 48.dp).wrapContentHeight(Alignment.CenterVertically),
                )
            }
        }
    }
}
