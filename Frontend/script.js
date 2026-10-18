
const API_URL = "http://127.0.0.1:8001/api/upload";
const INTERVAL_MS = 5000;

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
    if (!isRunning || isUploading) return;

    if (!video.videoWidth || !video.videoHeight) {
        setStatus("Waiting for the camera image...");
        return;
    }

    isUploading = true;

    try {
        // Capture one frame from the live video.
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        const context = canvas.getContext("2d");
        context.drawImage(video, 0, 0, canvas.width, canvas.height);

        const blob = await new Promise(resolve => {
            canvas.toBlob(resolve, "image/jpeg", 0.9);
        });

        if (!blob) {
            throw new Error("The browser could not create an image.");
        }

        // Show the captured frame independently of the API response.
        showPreview(blob);
        setStatus("Frame captured. Uploading to backend...");

        // Send the image as multipart/form-data.
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
        setStatus("Frame successfully saved to the backend.");

    } catch (error) {
        console.error("Capture/upload error:", error);
        setStatus(error.message || "An unexpected error occurred.", true);
        result.textContent = error.stack || error.message;
    } finally {
        isUploading = false;
    }
}

startBtn.addEventListener("click", async () => {
    if (isRunning) return;

    startBtn.disabled = true;
    setStatus("Requesting camera access...");

    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: "environment" } },
            audio: false
        });

        video.srcObject = stream;
        await video.play();

        isRunning = true;
        stopBtn.disabled = false;
        cameraBadge.textContent = "Running";
        cameraBadge.classList.add("active");

        setStatus("Camera running. Capturing the first frame...");

        // Capture immediately, then schedule subsequent captures.
        await captureAndUpload();

        if (isRunning) {
            captureTimer = setInterval(() => {
                captureAndUpload();
            }, INTERVAL_MS);
        }

    } catch (error) {
        console.error("Camera error:", error);
        setStatus(`Could not start camera: ${error.message}`, true);

        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }

        video.srcObject = null;
        isRunning = false;
        startBtn.disabled = false;
        stopBtn.disabled = true;
        cameraBadge.textContent = "Stopped";
        cameraBadge.classList.remove("active");
    }
});

stopBtn.addEventListener("click", () => {
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

    setStatus("Capture stopped.");
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
