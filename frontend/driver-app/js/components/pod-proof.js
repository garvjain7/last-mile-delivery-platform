import { escapeHTML } from "../state.js";

export function captureProofOfDelivery(stop, scannedAtStop = false) {
    return new Promise((resolve) => {
        const dialog = document.createElement("dialog");
        dialog.className = "action-dialog pod-dialog";
        dialog.innerHTML = `<form id="pod-form" method="dialog">
            <button class="dialog-close" type="button" data-pod-close aria-label="Close">×</button>
            <p class="eyebrow">PROOF OF DELIVERY</p>
            <h2>Handed to ${escapeHTML(stop.recipient)}?</h2>
            <p class="dialog-copy">A delivery photo is required. You can also add a signature or recipient name.</p>
            <div class="delivery-instructions" role="note"><strong>Customer instructions</strong><span>Instructions are not provided by the delivery service.</span></div>
            <p class="parcel-verified" role="status">${scannedAtStop ? "✓ Parcel scanned and matched to this stop" : "Parcel scan is completed from the active route before arrival."}</p>
            <div class="proof-method-grid" role="group" aria-label="Required photo and optional additional proof">
                <div class="proof-method proof-method-required" role="note"><span aria-hidden="true">▧</span><strong>Delivery photo · Required</strong></div>
                <button class="proof-method" type="button" data-proof-method="signature" aria-pressed="false"><span aria-hidden="true">✎</span><strong>Collect signature (optional)</strong></button>
                <button class="proof-method" type="button" data-proof-method="recipient_name" aria-pressed="false"><span aria-hidden="true">✓</span><strong>Recipient name (optional)</strong></button>
            </div>
            <input id="proof-method" type="hidden" value="none">
            <label id="recipient-name-label" class="field-label" for="recipient-name">Recipient name (optional)</label>
            <input id="recipient-name" class="text-input" maxlength="120" autocomplete="name" placeholder="Name of person receiving parcel">
            <label id="pod-photo-label" class="field-label" for="pod-photo">Delivery photo (required)</label>
            <div id="pod-camera" class="pod-camera">
                <video class="pod-camera-video" playsinline muted hidden></video>
                <img class="pod-camera-photo" alt="Captured proof-of-delivery photo" hidden>
                <div class="pod-camera-actions">
                    <button class="button button-secondary" type="button" data-camera-open>Open camera</button>
                    <button class="button button-primary" type="button" data-camera-capture hidden>Capture photo</button>
                    <button class="text-button" type="button" data-camera-close hidden>Close camera</button>
                </div>
                <p class="pod-camera-status" role="status" data-camera-status></p>
            </div>
            <input id="pod-photo" class="text-input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment">
            <div class="signature-wrap" hidden>
                <span class="field-label">Draw recipient signature</span>
                <canvas class="signature-pad" width="640" height="280" aria-label="Signature pad"></canvas>
                <button class="text-button" type="button" data-signature-clear>Clear signature</button>
            </div>
            <div id="pod-error" class="form-error" role="alert" hidden></div>
            <div class="dialog-actions">
                <button class="button button-secondary" type="button" data-pod-close>Cancel</button>
                <button class="button button-success" type="submit">Mark delivery successful</button>
            </div>
            <p class="dialog-footnote">Evidence uploads to private MinIO storage; the current database has no POD reference field.</p>
        </form>`;
        document.body.append(dialog);
        const form = dialog.querySelector("#pod-form");
        const method = dialog.querySelector("#proof-method");
        const nameInput = dialog.querySelector("#recipient-name");
        const photoInput = dialog.querySelector("#pod-photo");
        const cameraVideo = dialog.querySelector(".pod-camera-video");
        const cameraPhoto = dialog.querySelector(".pod-camera-photo");
        const cameraStatus = dialog.querySelector("[data-camera-status]");
        const cameraOpenButton = dialog.querySelector("[data-camera-open]");
        const cameraCaptureButton = dialog.querySelector("[data-camera-capture]");
        const cameraCloseButton = dialog.querySelector("[data-camera-close]");
        const nameLabel = dialog.querySelector("#recipient-name-label");
        const signatureWrap = dialog.querySelector(".signature-wrap");
        const canvas = dialog.querySelector(".signature-pad");
        const context = canvas.getContext("2d");
        let signed = false;
        let drawing = false;
        let result = null;
        let cameraStream = null;
        let capturedPhoto = null;
        let photoPreviewUrl = null;

        const close = (value = null) => {
            result = value;
            dialog.close();
        };
        const stopCamera = () => {
            if (cameraStream) cameraStream.getTracks().forEach((track) => track.stop());
            cameraStream = null;
            cameraVideo.srcObject = null;
            cameraVideo.hidden = true;
            cameraCaptureButton.hidden = true;
            cameraCloseButton.hidden = true;
            cameraOpenButton.hidden = false;
        };
        const clearPhotoPreview = () => {
            if (photoPreviewUrl) URL.revokeObjectURL(photoPreviewUrl);
            photoPreviewUrl = null;
            cameraPhoto.removeAttribute("src");
            cameraPhoto.hidden = true;
        };
        const startCamera = async () => {
            if (!navigator.mediaDevices?.getUserMedia) {
                cameraStatus.textContent = "Camera access is unavailable here. Choose a photo from your device instead.";
                return;
            }
            cameraOpenButton.disabled = true;
            cameraStatus.textContent = "Waiting for camera permission…";
            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: { ideal: "environment" } },
                    audio: false
                });
                if (!dialog.open) {
                    stream.getTracks().forEach((track) => track.stop());
                    return;
                }
                cameraStream = stream;
                cameraVideo.srcObject = stream;
                await cameraVideo.play();
                cameraVideo.hidden = false;
                cameraCaptureButton.hidden = false;
                cameraCloseButton.hidden = false;
                cameraOpenButton.hidden = true;
                cameraStatus.textContent = "Position the handoff in frame, then capture the photo.";
            } catch (error) {
                console.warn("Could not start the proof-of-delivery camera.", error);
                stopCamera();
                cameraStatus.textContent = "Camera could not start. Allow camera access or choose a photo instead.";
            } finally {
                cameraOpenButton.disabled = false;
            }
        };
        const updateMethod = () => {
            if (method.value !== "none" && method.value !== "signature" && method.value !== "recipient_name") {
                method.value = "none";
            }
            signatureWrap.hidden = method.value !== "signature";
            if (method.value !== "none") stopCamera();
            nameInput.setAttribute("aria-required", String(method.value === "recipient_name"));
            nameLabel.textContent = method.value === "recipient_name"
                ? "Additional recipient name (required)"
                : "Recipient name (optional)";
        };
        const point = (event) => {
            const bounds = canvas.getBoundingClientRect();
            return {
                x: (event.clientX - bounds.left) * (canvas.width / bounds.width),
                y: (event.clientY - bounds.top) * (canvas.height / bounds.height)
            };
        };
        const startDrawing = (event) => {
            event.preventDefault();
            drawing = true;
            canvas.setPointerCapture(event.pointerId);
            const position = point(event);
            context.beginPath();
            context.moveTo(position.x, position.y);
        };
        const draw = (event) => {
            if (!drawing) return;
            const position = point(event);
            context.lineWidth = 5;
            context.lineCap = "round";
            context.strokeStyle = "#192823";
            context.lineTo(position.x, position.y);
            context.stroke();
            signed = true;
        };
        const endDrawing = () => { drawing = false; };

        method.addEventListener("change", updateMethod);
        dialog.querySelectorAll("[data-proof-method]").forEach((button) => {
            button.addEventListener("click", () => {
                method.value = button.dataset.proofMethod;
                method.dispatchEvent(new Event("change"));
            });
        });
        updateMethod();
        dialog.querySelectorAll("[data-pod-close]").forEach((button) => {
            button.addEventListener("click", () => close());
        });
        dialog.querySelector("[data-signature-clear]").addEventListener("click", () => {
            context.clearRect(0, 0, canvas.width, canvas.height);
            signed = false;
        });
        cameraOpenButton.addEventListener("click", () => { void startCamera(); });
        cameraCloseButton.addEventListener("click", () => {
            stopCamera();
            cameraStatus.textContent = capturedPhoto
                ? "Photo captured. You can reopen the camera to retake it."
                : "Camera closed. Choose a photo from your device instead.";
        });
        cameraCaptureButton.addEventListener("click", async () => {
            if (!cameraVideo.videoWidth || !cameraVideo.videoHeight) {
                cameraStatus.textContent = "Camera is not ready yet. Please wait and try again.";
                return;
            }
            const scale = Math.min(1, 1920 / Math.max(cameraVideo.videoWidth, cameraVideo.videoHeight));
            const captureCanvas = document.createElement("canvas");
            captureCanvas.width = Math.round(cameraVideo.videoWidth * scale);
            captureCanvas.height = Math.round(cameraVideo.videoHeight * scale);
            captureCanvas.getContext("2d").drawImage(cameraVideo, 0, 0, captureCanvas.width, captureCanvas.height);
            const blob = await new Promise((done) => captureCanvas.toBlob(done, "image/jpeg", 0.88));
            if (!blob) {
                cameraStatus.textContent = "Could not capture the photo. Please try again.";
                return;
            }
            capturedPhoto = new File([blob], "delivery-photo.jpg", { type: "image/jpeg" });
            photoInput.value = "";
            clearPhotoPreview();
            photoPreviewUrl = URL.createObjectURL(capturedPhoto);
            cameraPhoto.src = photoPreviewUrl;
            cameraPhoto.hidden = false;
            stopCamera();
            cameraOpenButton.textContent = "Retake photo";
            cameraStatus.textContent = "Photo captured. Retake it or choose a different photo.";
        });
        photoInput.addEventListener("change", () => {
            if (!photoInput.files[0]) return;
            capturedPhoto = null;
            clearPhotoPreview();
            cameraStatus.textContent = "Photo selected from your device.";
        });
        const syncProofSelection = () => {
            dialog.querySelectorAll("[data-proof-method]").forEach((button) => {
                const selected = button.dataset.proofMethod === method.value;
                button.classList.toggle("is-selected", selected);
                button.setAttribute("aria-pressed", String(selected));
            });
        };
        method.addEventListener("change", syncProofSelection);
        canvas.addEventListener("pointerdown", startDrawing);
        canvas.addEventListener("pointermove", draw);
        canvas.addEventListener("pointerup", endDrawing);
        canvas.addEventListener("pointercancel", endDrawing);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const error = dialog.querySelector("#pod-error");
            error.hidden = true;
            const photoFile = capturedPhoto || photoInput.files[0];
            if (!photoFile || photoFile.size > 5 * 1024 * 1024) {
                error.textContent = photoFile ? "Photos must be 5 MB or smaller." : "Take or choose a delivery photo before marking this delivery successful.";
                error.hidden = false;
                return;
            }
            if (!["image/jpeg", "image/png", "image/webp"].includes(photoFile.type)) {
                error.textContent = "Choose a JPEG, PNG, or WebP photo.";
                error.hidden = false;
                return;
            }
            let signatureFile = null;
            if (method.value === "signature") {
                if (!signed) {
                    error.textContent = "Ask the recipient to sign in the box, or deselect the optional signature.";
                    error.hidden = false;
                    return;
                }
                signatureFile = await new Promise((done) => canvas.toBlob(done, "image/png"));
                if (!signatureFile) {
                    error.textContent = "Could not capture the signature. Please try again.";
                    error.hidden = false;
                    return;
                }
            } else if (method.value === "recipient_name" && !nameInput.value.trim()) {
                error.textContent = "Enter the additional recipient name or deselect that optional proof.";
                error.hidden = false;
                return;
            }
            close({
                file: photoFile,
                signatureFile,
                recipientName: nameInput.value.trim()
            });
        });
        dialog.addEventListener("close", () => {
            stopCamera();
            clearPhotoPreview();
            dialog.remove();
            resolve(result);
        }, { once: true });
        dialog.showModal();
    });
}
