import { escapeHTML } from "../state.js";

export function captureProofOfDelivery(stop) {
    return new Promise((resolve) => {
        const dialog = document.createElement("dialog");
        dialog.className = "action-dialog pod-dialog";
        dialog.innerHTML = `<form id="pod-form" method="dialog">
            <button class="dialog-close" type="button" data-pod-close aria-label="Close">×</button>
            <p class="eyebrow">PROOF OF DELIVERY</p>
            <h2>Handed to ${escapeHTML(stop.recipient)}?</h2>
            <p class="dialog-copy">Choose one proof method. A recipient name can also be added as a note.</p>
            <label class="field-label" for="proof-method">Proof method</label>
            <select id="proof-method" class="select-input">
                <option value="photo">Delivery photo</option>
                <option value="signature">Recipient signature</option>
                <option value="recipient_name">Recipient name</option>
            </select>
            <label class="field-label" for="recipient-name">Recipient name (optional)</label>
            <input id="recipient-name" class="text-input" maxlength="120" autocomplete="name" placeholder="Name of person receiving parcel">
            <label class="field-label" for="pod-photo">Take or choose photo</label>
            <input id="pod-photo" class="text-input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment">
            <div class="signature-wrap" hidden>
                <span class="field-label">Draw recipient signature</span>
                <canvas class="signature-pad" width="640" height="280" aria-label="Signature pad"></canvas>
                <button class="text-button" type="button" data-signature-clear>Clear signature</button>
            </div>
            <div id="pod-error" class="form-error" role="alert" hidden></div>
            <div class="dialog-actions">
                <button class="button button-secondary" type="button" data-pod-close>Cancel</button>
                <button class="button button-primary" type="submit">Save proof and delivery</button>
            </div>
            <p class="dialog-footnote">Evidence uploads to private MinIO storage; the current database has no POD reference field.</p>
        </form>`;
        document.body.append(dialog);
        const form = dialog.querySelector("#pod-form");
        const method = dialog.querySelector("#proof-method");
        const nameInput = dialog.querySelector("#recipient-name");
        const photoInput = dialog.querySelector("#pod-photo");
        const signatureWrap = dialog.querySelector(".signature-wrap");
        const canvas = dialog.querySelector(".signature-pad");
        const context = canvas.getContext("2d");
        let signed = false;
        let drawing = false;
        let result = null;

        const close = (value = null) => {
            result = value;
            dialog.close();
        };
        const updateMethod = () => {
            signatureWrap.hidden = method.value !== "signature";
            photoInput.hidden = method.value !== "photo";
        };
        const point = (event) => {
            const bounds = canvas.getBoundingClientRect();
            return {
                x: (event.clientX - bounds.left) * (canvas.width / bounds.width),
                y: (event.clientY - bounds.top) * (canvas.height / bounds.height)
            };
        };
        const startDrawing = (event) => {
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
        updateMethod();
        dialog.querySelectorAll("[data-pod-close]").forEach((button) => {
            button.addEventListener("click", () => close());
        });
        dialog.querySelector("[data-signature-clear]").addEventListener("click", () => {
            context.clearRect(0, 0, canvas.width, canvas.height);
            signed = false;
        });
        canvas.addEventListener("pointerdown", startDrawing);
        canvas.addEventListener("pointermove", draw);
        canvas.addEventListener("pointerup", endDrawing);
        canvas.addEventListener("pointercancel", endDrawing);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const error = dialog.querySelector("#pod-error");
            error.hidden = true;
            let file;
            if (method.value === "photo") {
                file = photoInput.files[0];
                if (!file || file.size > 5 * 1024 * 1024) {
                    error.textContent = file ? "Photos must be 5 MB or smaller." : "Add a photo or choose another proof method.";
                    error.hidden = false;
                    return;
                }
                if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
                    error.textContent = "Choose a JPEG, PNG, or WebP photo.";
                    error.hidden = false;
                    return;
                }
            } else if (method.value === "signature") {
                if (!signed) {
                    error.textContent = "Ask the recipient to sign in the box, or choose another proof method.";
                    error.hidden = false;
                    return;
                }
                file = await new Promise((done) => canvas.toBlob(done, "image/png"));
                if (!file) {
                    error.textContent = "Could not capture the signature. Please try again.";
                    error.hidden = false;
                    return;
                }
            } else if (!nameInput.value.trim()) {
                error.textContent = "Enter the recipient name or choose another proof method.";
                error.hidden = false;
                return;
            }
            close({
                evidenceType: method.value,
                file,
                recipientName: nameInput.value.trim()
            });
        });
        dialog.addEventListener("close", () => {
            dialog.remove();
            resolve(result);
        }, { once: true });
        dialog.showModal();
    });
}

export function captureException(stop) {
    return new Promise((resolve) => {
        const dialog = document.createElement("dialog");
        dialog.className = "action-dialog";
        dialog.innerHTML = `<form id="exception-form" method="dialog">
            <button class="dialog-close" type="button" data-exception-close aria-label="Close">×</button>
            <p class="eyebrow">DELIVERY EXCEPTION</p><h2>What happened?</h2>
            <p class="dialog-copy">${escapeHTML(stop.recipient)} · ${escapeHTML(stop.address)}</p>
            <label class="field-label" for="failure-reason">Reason</label>
            <select id="failure-reason" name="failure_reason" class="select-input">
                <option value="recipient_unavailable">Recipient unavailable</option>
                <option value="wrong_address">Wrong address</option>
                <option value="refused">Delivery refused</option>
                <option value="other">Other</option>
            </select>
            <label class="field-label" for="failure-notes">Notes (optional)</label>
            <textarea id="failure-notes" name="failure_notes" class="text-input" maxlength="500" rows="3"></textarea>
            <label class="field-label" for="exception-photo">Photo (optional)</label>
            <input id="exception-photo" name="photo" class="text-input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment">
            <div id="exception-error" class="form-error" role="alert" hidden></div>
            <label class="check-label"><input name="return_to_hub" type="checkbox"><span>Mark order as returned to hub</span></label>
            <p class="dialog-footnote">Return dispatch and photo references are not stored in the current database schema.</p>
            <div class="dialog-actions">
                <button class="button button-secondary" type="button" data-exception-close>Cancel</button>
                <button class="button button-primary" type="submit">Save exception</button>
            </div>
        </form>`;
        document.body.append(dialog);
        const form = dialog.querySelector("#exception-form");
        let result = null;
        const close = (value = null) => {
            result = value;
            dialog.close();
        };
        dialog.querySelectorAll("[data-exception-close]").forEach((button) => {
            button.addEventListener("click", () => close());
        });
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const values = new FormData(form);
            const photo = values.get("photo");
            const error = dialog.querySelector("#exception-error");
            if (photo instanceof File && photo.size > 0 && photo.size > 5 * 1024 * 1024) {
                error.textContent = "Exception photos must be 5 MB or smaller.";
                error.hidden = false;
                return;
            }
            if (
                photo instanceof File
                && photo.size > 0
                && !["image/jpeg", "image/png", "image/webp"].includes(photo.type)
            ) {
                error.textContent = "Choose a JPEG, PNG, or WebP photo.";
                error.hidden = false;
                return;
            }
            close({
                failureReason: values.get("failure_reason"),
                failureNotes: values.get("failure_notes").trim(),
                returnToHub: values.has("return_to_hub"),
                photo
            });
        });
        dialog.addEventListener("close", () => {
            dialog.remove();
            resolve(result);
        }, { once: true });
        dialog.showModal();
    });
}
