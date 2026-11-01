
const API_URL = "/api/upload";
const INTERVAL_MS = 3000;
const MAX_FRAMES_PER_SESSION = 3;

const video = document.getElementById("video");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const cameraBadge = document.getElementById("cameraBadge");
const frameBadge = document.getElementById("frameBadge");
const statusText = document.getElementById("status");
const preview = document.getElementById("preview");
const previewPlaceholder = document.getElementById("previewPlaceholder");
const frameCountText = document.getElementById("frameCount");
const lastCaptureText = document.getElementById("lastCapture");
const result = document.getElementById("result");

let stream = null;
let isRunning = false;
let isUploading = false;
let captureTimer = null;
let successfulFrames = 0;
let previewUrl = null;

// Set while a voice-triggered visual question is capturing images.
let captureForAnalysis = null;

function setStatus(message, isError = false) {
    statusText.textContent = message;
    statusText.classList.toggle("error", isError);
}

function stopCaptureTimer() {
    if (captureTimer !== null) {
        clearInterval(captureTimer);
        captureTimer = null;
    }
}

function showPreview(blob) {
    if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
    }

    previewUrl = URL.createObjectURL(blob);

    preview.onload = () => {
        previewPlaceholder.hidden = true;
        preview.hidden = false;
    };

    preview.onerror = () => {
        preview.hidden = true;
        previewPlaceholder.hidden = false;
        previewPlaceholder.textContent =
            "Could not display the captured frame.";
    };

    preview.src = previewUrl;
}

async function captureAndUpload() {
    if (!isRunning || isUploading) {
        return false;
    }

    if (!video.videoWidth || !video.videoHeight) {
        setStatus("Waiting for the camera image...");
        return false;
    }

    isUploading = true;

    try {
        // Capture one frame from the live video.
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        const context = canvas.getContext("2d");

        if (!context) {
            throw new Error("Could not create the image canvas.");
        }

        context.drawImage(
            video,
            0,
            0,
            canvas.width,
            canvas.height
        );

        const blob = await new Promise(resolve => {
            canvas.toBlob(resolve, "image/jpeg", 0.9);
        });

        if (!blob) {
            throw new Error("The browser could not create an image.");
        }

        showPreview(blob);
        setStatus("Frame captured. Uploading to backend...");

        // Upload the captured frame.
        const formData = new FormData();
        formData.append("file", blob, "frame.jpg");

        const response = await fetch(API_URL, {
            method: "POST",
            body: formData
        });

        const responseText = await response.text();
        let data;

        try {
            data = JSON.parse(responseText);
        } catch {
            throw new Error(
                `Backend returned an invalid response (HTTP ${response.status}).`
            );
        }

        if (!response.ok) {
            throw new Error(
                data.detail || `Upload failed (HTTP ${response.status}).`
            );
        }

        successfulFrames++;

        frameCountText.textContent =
            `${successfulFrames} ${successfulFrames === 1 ? "frame" : "frames"}`;

        frameBadge.textContent = "Saved";
        frameBadge.classList.add("active");

        lastCaptureText.textContent =
            `Latest saved image: ${data.filename || "Frame received"}`;

        result.textContent = JSON.stringify(data, null, 2);

        setStatus(
            `Image uploaded successfully (${successfulFrames}/${MAX_FRAMES_PER_SESSION}).`
        );

        return true;

    } catch (error) {
        console.error("Capture/upload error:", error);

        setStatus(
            error.message || "An unexpected error occurred.",
            true
        );

        result.textContent = error.stack || error.message;

        return false;

    } finally {
        isUploading = false;
    }
}

// Wait until the browser has actual video dimensions before capturing.
function waitForVideoReady() {
    return new Promise((resolve, reject) => {
        if (
            video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
            video.videoWidth > 0 &&
            video.videoHeight > 0
        ) {
            resolve();
            return;
        }

        const timeout = setTimeout(() => {
            cleanup();

            reject(
                new Error(
                    "Camera started, but no video frame became available."
                )
            );
        }, 10000);

        function cleanup() {
            clearTimeout(timeout);
            video.removeEventListener("loadeddata", checkReady);
            video.removeEventListener("playing", checkReady);
        }

        function checkReady() {
            if (
                video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
                video.videoWidth > 0 &&
                video.videoHeight > 0
            ) {
                cleanup();
                resolve();
            }
        }

        video.addEventListener("loadeddata", checkReady);
        video.addEventListener("playing", checkReady);

        checkReady();
    });
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function startCamera() {
    if (isRunning) {
        return false;
    }

    startBtn.disabled = true;
    setStatus("Requesting camera access...");

    try {
        if (!navigator.mediaDevices?.getUserMedia) {
            throw new Error(
                "Camera access is not supported here. Use HTTPS or localhost."
            );
        }

        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: {
                    ideal: "environment"
                }
            },
            audio: false
        });

        video.srcObject = stream;

        await video.play();
        await waitForVideoReady();

        isRunning = true;

        stopBtn.disabled = false;
        cameraBadge.textContent = "Running";
        cameraBadge.classList.add("active");

        // Capture 3 images total.
        // Capture the first immediately, then wait 3 seconds
        // between the second and third images.
        let uploadedFrames = 0;

        for (let i = 0; i < MAX_FRAMES_PER_SESSION; i++) {
            if (!isRunning) {
                throw new Error(
                    "Camera capture was stopped before all images were captured."
                );
            }

            if (i > 0) {
                setStatus(
                    `Waiting ${INTERVAL_MS / 1000} seconds before image ` +
                    `${i + 1} of ${MAX_FRAMES_PER_SESSION}...`
                );

                await delay(INTERVAL_MS);
            }

            if (!isRunning) {
                throw new Error("Camera capture was stopped.");
            }

            const uploaded = await captureAndUpload();

            if (!uploaded) {
                throw new Error(
                    `Image ${i + 1} could not be captured or uploaded.`
                );
            }

            uploadedFrames++;

            setStatus(
                `Uploaded image ${uploadedFrames} of ${MAX_FRAMES_PER_SESSION}.`
            );
        }

        stopCamera("Captured 3 images. Camera stopped automatically.");

        return uploadedFrames === MAX_FRAMES_PER_SESSION;

    } catch (error) {
        console.error("Camera error:", error);

        setStatus(
            `Could not complete camera capture: ${error.message}`,
            true
        );

        stopCamera("Camera stopped because capture failed.");

        return false;
    }
}

// Manual start button and voice-triggered capture use the same function.
startBtn.addEventListener("click", async () => {
    const uploaded = await startCamera();

    if (captureForAnalysis) {
        const resolveCapture = captureForAnalysis;
        captureForAnalysis = null;
        resolveCapture(uploaded);
    }
});

function stopCamera(message = "Capture stopped.") {
    isRunning = false;

    stopCaptureTimer();

    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
    }

    video.srcObject = null;

    startBtn.disabled = false;
    stopBtn.disabled = true;

    cameraBadge.textContent = "Stopped";
    cameraBadge.classList.remove("active");

    setStatus(message);
}

// Stop camera and any scheduled captures.
stopBtn.addEventListener("click", () => {
    stopCamera("Capture stopped.");
});

window.addEventListener("beforeunload", () => {
    stopCaptureTimer();

    if (stream) {
        stream.getTracks().forEach(track => track.stop());
    }

    if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
    }
});

(() => {
    const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

    const startBtn = document.getElementById("startVoiceBtn");
    const stopBtn = document.getElementById("stopVoiceBtn");
    const statusEl = document.getElementById("voiceStatus");
    const transcriptEl = document.getElementById("voiceTranscript");

    if (!startBtn || !stopBtn || !statusEl || !transcriptEl) {
        console.error("[Voice] Required HTML elements were not found.");
        return;
    }

    const WAKE_PHRASE = "hello vision";

    let running = false;
    let mode = "off";
    let recognition = null;
    let restartTimer = null;
    let commandTranscript = "";
    let wakeDetected = false;
    let session = 0;

    // Play a short sound when listening starts or finishes.
    function playBeep(type = "start") {
        try {
            const AudioContextClass =
                window.AudioContext ||
                window.webkitAudioContext;

            if (!AudioContextClass) {
                return;
            }

            const audioContext = new AudioContextClass();
            const oscillator = audioContext.createOscillator();
            const gain = audioContext.createGain();

            oscillator.connect(gain);
            gain.connect(audioContext.destination);

            const now = audioContext.currentTime;

            if (type === "start") {
                oscillator.frequency.setValueAtTime(660, now);
                oscillator.frequency.setValueAtTime(880, now + 0.12);
            } else {
                oscillator.frequency.setValueAtTime(880, now);
                oscillator.frequency.setValueAtTime(660, now + 0.12);
            }

            oscillator.type = "sine";

            gain.gain.setValueAtTime(0.001, now);
            gain.gain.linearRampToValueAtTime(0.15, now + 0.02);
            gain.gain.setValueAtTime(0.15, now + 0.15);
            gain.gain.linearRampToValueAtTime(0.001, now + 0.25);

            oscillator.start(now);
            oscillator.stop(now + 0.26);

            oscillator.onended = () => {
                audioContext.close().catch(() => {});
            };

        } catch (error) {
            console.warn("[Voice] Beep could not play:", error);
        }
    }

    function setStatus(message) {
        statusEl.textContent = message;
        console.log("[Voice]", message);
    }

    function clearRestart() {
        if (restartTimer !== null) {
            clearTimeout(restartTimer);
            restartTimer = null;
        }
    }

    // Text-to-speech.
    function speakText(text) {
        if (!("speechSynthesis" in window)) {
            console.error(
                "Text-to-speech is not supported in this browser."
            );
            return;
        }

        const message = String(text ?? "").trim();

        if (!message) {
            return;
        }

        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(message);

        utterance.lang = "en-IN";
        utterance.rate = 0.95;
        utterance.pitch = 1;
        utterance.volume = 1;

        window.speechSynthesis.speak(utterance);
    }

    function createRecognition(continuous, interimResults) {
        const instance = new SpeechRecognition();

        instance.lang = "en-US";
        instance.continuous = continuous;
        instance.interimResults = interimResults;
        instance.maxAlternatives = 1;

        return instance;
    }

    function stopRecognition() {
        if (!recognition) {
            return;
        }

        const current = recognition;
        recognition = null;

        try {
            current.abort();
        } catch (error) {
            console.warn("[Voice] Recognition stop error:", error);
        }
    }

    // Phase 1: Continuously listen for "Hello Vision".
    function startWakeListening() {
        if (!running || mode !== "wake") {
            return;
        }

        clearRestart();

        const mySession = ++session;
        const instance = createRecognition(true, true);

        recognition = instance;
        wakeDetected = false;

        setStatus('Listening for wake phrase: "Hello Vision".');

        instance.onresult = event => {
            if (
                !running ||
                mySession !== session ||
                mode !== "wake"
            ) {
                return;
            }

            for (
                let i = event.resultIndex;
                i < event.results.length;
                i++
            ) {
                const result = event.results[i];
                const text = result[0].transcript.toLowerCase().trim();

                console.log("[Wake detection]", text);

                if (result.isFinal && text.includes(WAKE_PHRASE)) {
                    wakeDetected = true;
                    mode = "switching";

                    setStatus('Wake phrase detected: "Hello Vision".');

                    instance.stop();
                    return;
                }
            }
        };

        instance.onerror = event => {
            console.warn(
                "[Voice] Wake recognition error:",
                event.error
            );

            if (
                event.error === "not-allowed" ||
                event.error === "service-not-allowed"
            ) {
                running = false;
                mode = "off";

                startBtn.disabled = false;
                stopBtn.disabled = true;

                setStatus("Microphone permission denied.");
            }
        };

        instance.onend = () => {
            if (!running || mySession !== session) {
                return;
            }

            if (wakeDetected && mode === "switching") {
                recognition = null;
                mode = "command";

                playBeep("start");

                setStatus(
                    "Wake detected. Listening for your question..."
                );

                restartTimer = setTimeout(() => {
                    restartTimer = null;

                    if (running && mode === "command") {
                        startCommandListening();
                    }
                }, 450);

            } else if (mode === "wake") {
                restartTimer = setTimeout(() => {
                    restartTimer = null;

                    if (running && mode === "wake") {
                        startWakeListening();
                    }
                }, 300);
            }
        };

        try {
            instance.start();
        } catch (error) {
            console.error(
                "[Voice] Could not start wake recognition:",
                error
            );
        }
    }

    // Phase 2: Listen for the user's question.
    function startCommandListening() {
        if (!running || mode !== "command") {
            return;
        }

        clearRestart();

        const mySession = ++session;
        const instance = createRecognition(false, true);

        recognition = instance;
        commandTranscript = "";

        setStatus("Listening for your question. Speak now.");

        instance.onresult = event => {
            if (
                !running ||
                mySession !== session ||
                mode !== "command"
            ) {
                return;
            }

            for (
                let i = event.resultIndex;
                i < event.results.length;
                i++
            ) {
                const result = event.results[i];

                if (result.isFinal) {
                    commandTranscript = result[0].transcript.trim();

                    console.log(
                        "[Recognized question]",
                        commandTranscript
                    );

                    transcriptEl.textContent =
                        commandTranscript || "No speech detected.";
                }
            }
        };

        instance.onerror = event => {
            console.warn(
                "[Voice] Command recognition error:",
                event.error
            );
        };

        // Phase 3: Send the recognized question to the backend.
        instance.onend = async () => {
            if (
                !running ||
                mySession !== session ||
                mode !== "command"
            ) {
                return;
            }

            recognition = null;
            mode = "processing";

            console.log(
                "[Final question]",
                commandTranscript || "(no speech recognized)"
            );

            playBeep("finish");

            if (!commandTranscript.trim()) {
                setStatus(
                    'No question detected. Say "Hello Vision" to try again.'
                );

                restartTimer = setTimeout(() => {
                    restartTimer = null;

                    if (running && mode === "processing") {
                        mode = "wake";
                        startWakeListening();
                    }
                }, 500);

                return;
            }

            setStatus("Sending your question to the backend...");

            try {
                // First, classify the question on the backend.
                const response = await fetch("/api/ask", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        question: commandTranscript.trim()
                    })
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.detail ||
                        `Request failed with HTTP ${response.status}`
                    );
                }

                let finalAnswer = data.answer || "";

                // Visual questions need fresh camera images.
                if (data.action === "capture_image") {
                    setStatus(
                        "Opening the camera to capture 3 images..."
                    );

                    // Stop regular camera mode if it is already running.
                    if (isRunning) {
                        stopCamera("Restarting camera for visual analysis.");
                    }

                    // Call the camera function directly, rather than
                    // simulating a click on the camera start button.
                    const uploaded = await startCamera();

                    if (!uploaded) {
                        throw new Error(
                            "Could not capture and upload all 3 images. " +
                            "Check camera permission and try again."
                        );
                    }

                    setStatus(
                        "Three images uploaded. Analyzing the scene..."
                    );

                    // Analyze the uploaded images through the backend.
                    const analysisResponse = await fetch("/api/analyze", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            category: data.category,
                            question: commandTranscript.trim()
                        })
                    });

                    const analysisData = await analysisResponse.json();

                    if (!analysisResponse.ok) {
                        throw new Error(
                            analysisData.detail ||
                            `Analysis failed with HTTP ${analysisResponse.status}`
                        );
                    }

                    finalAnswer = analysisData.answer ||
                        "I couldn't find an answer in the captured image.";
                }

                // Speak the answer.
                speakText(finalAnswer);

                console.log("[Backend answer]", finalAnswer);
                console.log("[Category]", data.category);
                console.log("[Action]", data.action);

                transcriptEl.textContent =
                    `You asked: ${commandTranscript}\n\n` +
                    `Vision Assistant: ${
                        finalAnswer || "No answer returned."
                    }`;

                setStatus("Answer received successfully.");

            } catch (error) {
                console.error(
                    "[Backend request failed]",
                    error
                );

                transcriptEl.textContent =
                    `You asked: ${commandTranscript}\n\n` +
                    `Error: ${error.message}`;

                setStatus(
                    `Backend request failed: ${error.message}`
                );

            } finally {
                if (running) {
                    restartTimer = setTimeout(() => {
                        restartTimer = null;

                        if (running && mode === "processing") {
                            mode = "wake";
                            startWakeListening();
                        }
                    }, 700);
                }
            }
        };

        try {
            instance.start();
        } catch (error) {
            console.error(
                "[Voice] Could not start command recognition:",
                error
            );

            recognition = null;
            mode = "wake";

            if (running) {
                restartTimer = setTimeout(() => {
                    restartTimer = null;
                    startWakeListening();
                }, 500);
            }
        }
    }

    // Start the voice assistant.
    startBtn.addEventListener("click", async () => {
        if (!SpeechRecognition) {
            setStatus(
                "Speech recognition is not supported in this browser."
            );
            return;
        }

        if (running) {
            return;
        }

        running = true;
        mode = "wake";

        startBtn.disabled = true;
        stopBtn.disabled = false;

        // Unlock audio after the user's button interaction.
        try {
            const AudioContextClass =
                window.AudioContext ||
                window.webkitAudioContext;

            if (AudioContextClass) {
                const audioContext = new AudioContextClass();

                await audioContext.resume();
                await audioContext.close();
            }
        } catch (error) {
            console.warn(
                "[Voice] Audio initialization warning:",
                error
            );
        }

        if (running) {
            startWakeListening();
        }
    });

    // Stop listening and prevent automatic restarts.
    stopBtn.addEventListener("click", () => {
        running = false;
        mode = "off";
        session++;

        clearRestart();
        stopRecognition();

        startBtn.disabled = false;
        stopBtn.disabled = true;

        setStatus("Voice assistant stopped.");

        console.log("[Voice] Assistant stopped by user.");
    });

    stopBtn.disabled = true;

    console.log("[Voice] Voice assistant initialized.");
})();
