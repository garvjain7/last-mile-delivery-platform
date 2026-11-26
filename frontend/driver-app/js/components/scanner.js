export function showScanWarning(message) {
    const dialog = document.createElement("dialog");
    dialog.className = "action-dialog scan-warning-dialog";
    dialog.innerHTML = `<p class="eyebrow">PACKAGE NOT VERIFIED</p>
        <h2>Check this parcel</h2>
        <p class="dialog-copy scan-warning-message"></p>
        <button class="button button-primary button-wide" type="button">Try again</button>`;
    dialog.querySelector(".scan-warning-message").textContent = message;
    dialog.querySelector("button").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    document.body.append(dialog);
    dialog.showModal();
}

export function scanBarcode(title = "Scan parcel barcode", manifestTrackingToken = "") {
    return new Promise((resolve) => {
        const dialog = document.createElement("dialog");
        dialog.className = "action-dialog scanner-dialog";
        dialog.innerHTML = `<form id="barcode-form" method="dialog">
            <button class="dialog-close" type="button" data-scanner-close aria-label="Close">×</button>
            <p class="eyebrow">PARCEL SCAN</p><h2>${title}</h2>
            <video class="scanner-video" playsinline muted hidden></video>
            <div class="scanner-camera-controls">
                <button class="button button-secondary" type="button" data-camera-open>
                    <svg class="scanner-camera-icon" viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M4 7h3l1.5-2h8L18 7h2v12H4z"></path>
                        <circle cx="12" cy="13" r="3.5"></circle>
                    </svg>
                    <span>Open camera</span>
                </button>
                <button class="button button-secondary" type="button" data-camera-close hidden>Close camera</button>
            </div>
            <p class="scanner-status" role="status">Open the camera to scan a barcode automatically, or enter the tracking number manually.</p>
            <label class="field-label" for="tracking-code">Tracking number</label>
            <input id="tracking-code" name="tracking_code" class="text-input" autocomplete="off" autocapitalize="characters" required>
            ${manifestTrackingToken ? `<button class="scanner-demo-button" type="button" data-manifest-barcode>Fill barcode from route</button>` : ""}
            <div class="dialog-actions">
                <button class="button button-secondary" type="button" data-scanner-close>Cancel</button>
                <button class="button button-primary" type="submit">Verify parcel</button>
            </div>
        </form>`;
        document.body.append(dialog);
        const form = dialog.querySelector("#barcode-form");
        const video = dialog.querySelector(".scanner-video");
        const status = dialog.querySelector(".scanner-status");
        const input = dialog.querySelector("#tracking-code");
        const openCameraButton = dialog.querySelector("[data-camera-open]");
        const closeCameraButton = dialog.querySelector("[data-camera-close]");
        let stream = null;
        let animationFrame = null;
        let result = null;
        let detector = null;
        let detecting = false;
        let decoderControls = null;
        let decodedBeforeCameraReady = "";

        const stopCamera = () => {
            if (animationFrame !== null) cancelAnimationFrame(animationFrame);
            animationFrame = null;
            if (decoderControls) decoderControls.stop();
            decoderControls = null;
            if (stream) stream.getTracks().forEach((track) => track.stop());
            stream = null;
            video.pause();
            video.srcObject = null;
            video.hidden = true;
            openCameraButton.hidden = false;
            openCameraButton.disabled = false;
            closeCameraButton.hidden = true;
        };
        const acceptBarcode = (value) => {
            input.value = value;
            status.textContent = `Barcode detected: ${value}. Select Verify parcel.`;
            if (decoderControls || stream) stopCamera();
            else decodedBeforeCameraReady = value;
        };
        const detectFrame = async () => {
            if (dialog.open && detector && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && !detecting) {
                detecting = true;
                try {
                    const codes = await detector.detect(video);
                    if (codes[0]?.rawValue) {
                        acceptBarcode(codes[0].rawValue);
                        return;
                    }
                } catch (error) {
                    console.warn("Camera barcode detection failed; manual entry remains available.", error);
                } finally {
                    detecting = false;
                }
            }
            if (dialog.open && stream) animationFrame = requestAnimationFrame(detectFrame);
        };
        const finish = (value) => {
            result = value;
            dialog.close();
        };

        dialog.querySelectorAll("[data-scanner-close]").forEach((button) => {
            button.addEventListener("click", () => finish(null));
        });
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            if (!form.reportValidity()) return;
            finish(input.value.trim());
        });
        dialog.querySelector("[data-manifest-barcode]")?.addEventListener("click", () => {
            stopCamera();
            input.value = manifestTrackingToken;
            status.textContent = `Route barcode ready: ${manifestTrackingToken}. Select Verify parcel.`;
            input.focus();
        });
        openCameraButton.addEventListener("click", async () => {
            if (!navigator.mediaDevices?.getUserMedia) {
                status.textContent = "Camera is unavailable here. Enter the barcode number manually.";
                return;
            }
            openCameraButton.disabled = true;
            decodedBeforeCameraReady = "";
            status.textContent = "Starting camera barcode scanner…";
            try {
                if (!("BarcodeDetector" in window)) {
                    const { BrowserMultiFormatReader, BarcodeFormat, DecodeHintType } = await import("../services/barcode-scanner.js");
                    if (!dialog.open) return;
                    video.hidden = false;
                    const hints = new Map([
                        [DecodeHintType.POSSIBLE_FORMATS, [
                            BarcodeFormat.QR_CODE,
                            BarcodeFormat.CODE_128,
                            BarcodeFormat.CODE_39,
                            BarcodeFormat.EAN_13,
                            BarcodeFormat.EAN_8,
                            BarcodeFormat.UPC_A,
                            BarcodeFormat.UPC_E
                        ]],
                        [DecodeHintType.TRY_HARDER, true]
                    ]);
                    const reader = new BrowserMultiFormatReader(hints, 200);
                    const controls = await reader.decodeFromConstraints({
                        video: { facingMode: { ideal: "environment" } },
                        audio: false
                    }, video, (code) => {
                        if (code?.getText()) acceptBarcode(code.getText());
                    });
                    if (!dialog.open) {
                        controls.stop();
                        return;
                    }
                    decoderControls = controls;
                    openCameraButton.hidden = true;
                    closeCameraButton.hidden = false;
                    status.textContent = decodedBeforeCameraReady
                        ? `Barcode detected: ${decodedBeforeCameraReady}. Select Verify parcel.`
                        : "Camera is scanning. Hold a barcode in view or enter it manually below.";
                    if (decodedBeforeCameraReady) stopCamera();
                    return;
                }
                try {
                    detector = new window.BarcodeDetector({
                        formats: ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "upc_a", "upc_e"]
                    });
                } catch {
                    detector = new window.BarcodeDetector();
                }
                const cameraStream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: { ideal: "environment" } },
                    audio: false
                });
                if (!dialog.open) {
                    cameraStream.getTracks().forEach((track) => track.stop());
                    return;
                }
                stream = cameraStream;
                video.srcObject = stream;
                await video.play();
                if (!dialog.open) {
                    stopCamera();
                    return;
                }
                video.hidden = false;
                openCameraButton.hidden = true;
                closeCameraButton.hidden = false;
                status.textContent = "Camera is scanning. Hold a barcode in view or enter it manually below.";
                animationFrame = requestAnimationFrame(detectFrame);
            } catch (error) {
                stopCamera();
                status.textContent = "Camera scanner unavailable. Allow camera access or enter the barcode manually.";
                console.warn("Could not start the parcel camera preview.", error);
            }
        });
        closeCameraButton.addEventListener("click", () => {
            stopCamera();
            status.textContent = "Camera closed. Enter the barcode manually or reopen the camera.";
        });
        dialog.addEventListener("close", () => {
            stopCamera();
            dialog.remove();
            resolve(result);
        }, { once: true });
        dialog.showModal();
        input.focus();
    });
}
