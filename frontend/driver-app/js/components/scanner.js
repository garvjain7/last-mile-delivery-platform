export function scanBarcode(title = "Scan parcel barcode") {
    return new Promise((resolve) => {
        const dialog = document.createElement("dialog");
        dialog.className = "action-dialog scanner-dialog";
        dialog.innerHTML = `<form id="barcode-form" method="dialog">
            <button class="dialog-close" type="button" data-scanner-close aria-label="Close">×</button>
            <p class="eyebrow">PARCEL SCAN</p><h2>${title}</h2>
            <video class="scanner-video" playsinline muted hidden></video>
            <p class="scanner-status" role="status">Camera scan or enter the tracking number.</p>
            <label class="field-label" for="tracking-code">Tracking number</label>
            <input id="tracking-code" name="tracking_code" class="text-input" autocomplete="off" autocapitalize="characters" required>
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
        let stream = null;
        let animationFrame = null;
        let result = null;
        let detector = null;
        let detecting = false;

        const stopCamera = () => {
            if (animationFrame !== null) cancelAnimationFrame(animationFrame);
            if (stream) stream.getTracks().forEach((track) => track.stop());
            video.srcObject = null;
        };
        const finish = (value) => {
            result = value;
            dialog.close();
        };
        const detectFrame = async () => {
            if (dialog.open && detector && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
                if (!detecting) {
                    detecting = true;
                    try {
                        const codes = await detector.detect(video);
                        if (codes[0]?.rawValue) {
                            finish(codes[0].rawValue);
                            return;
                        }
                    } catch (error) {
                        console.warn("Camera barcode detection failed; manual entry remains available.", error);
                    } finally {
                        detecting = false;
                    }
                }
            }
            if (dialog.open) animationFrame = requestAnimationFrame(detectFrame);
        };

        dialog.querySelectorAll("[data-scanner-close]").forEach((button) => {
            button.addEventListener("click", () => finish(null));
        });
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            if (!form.reportValidity()) return;
            finish(input.value.trim());
        });
        dialog.addEventListener("close", () => {
            stopCamera();
            dialog.remove();
            resolve(result);
        }, { once: true });
        dialog.showModal();
        input.focus();

        const startCamera = async () => {
            if (!("BarcodeDetector" in window) || !navigator.mediaDevices?.getUserMedia) {
                status.textContent = "Camera scanning is not supported here. Enter the tracking number below.";
                return;
            }
            try {
                try {
                    detector = new window.BarcodeDetector({
                        formats: ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "upc_a", "upc_e"]
                    });
                } catch {
                    detector = new window.BarcodeDetector();
                }
                stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: { ideal: "environment" } },
                    audio: false
                });
                if (!dialog.open) {
                    stopCamera();
                    return;
                }
                video.srcObject = stream;
                video.hidden = false;
                await video.play();
                status.textContent = "Hold the barcode inside the camera frame.";
                animationFrame = requestAnimationFrame(detectFrame);
            } catch (error) {
                stopCamera();
                detector = null;
                status.textContent = "Camera unavailable. Enter the tracking number manually.";
                console.warn("Could not start the parcel camera scanner.", error);
            }
        };
        void startCamera();
    });
}
