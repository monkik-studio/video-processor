const dropzone = document.getElementById("dropzone");
const videoInput = document.getElementById("video");
const selectedFile = document.getElementById("selectedFile");

if (dropzone && videoInput) {
  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("is-dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("is-dragover");
    });
  });

  dropzone.addEventListener("drop", (event) => {
    if (event.dataTransfer.files.length) {
      videoInput.files = event.dataTransfer.files;
      selectedFile.textContent = summarizeFiles(event.dataTransfer.files);
    }
  });

  videoInput.addEventListener("change", () => {
    selectedFile.textContent = videoInput.files.length ? summarizeFiles(videoInput.files) : "";
  });

  function summarizeFiles(files) {
    if (files.length === 1) {
      return files[0].name;
    }
    return `${files.length} files selected`;
  }
}

const processForm = document.getElementById("processForm");

if (processForm) {
  const progressWrap = document.getElementById("progressWrap");
  const progressBar = document.getElementById("progressBar");
  const processButton = document.getElementById("processButton");
  const errorBox = document.getElementById("errorBox");
  const resultPanel = document.getElementById("resultPanel");
  const previewVideo = document.getElementById("previewVideo");
  const downloadButton = document.getElementById("downloadButton");
  const zipButton = document.getElementById("zipButton");
  const outputList = document.getElementById("outputList");
  const metadataBox = document.getElementById("metadataBox");
  const batchProgressList = document.getElementById("batchProgressList");
  const youtubeTitle = document.getElementById("youtubeTitle");
  const youtubeDescription = document.getElementById("youtubeDescription");
  const youtubeKeywords = document.getElementById("youtubeKeywords");
  const fileInputs = Array.from(document.querySelectorAll('input[name="filenames"]'));

  processForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.add("d-none");
    resultPanel.classList.add("d-none");
    progressWrap.classList.remove("d-none");
    batchProgressList.classList.remove("d-none");
    processButton.disabled = true;
    outputList.innerHTML = "";
    metadataBox.textContent = "";
    downloadButton.classList.add("d-none");
    zipButton.classList.add("d-none");
    resetBatchProgress();

    const results = [];
    const failures = [];

    try {
      for (let index = 0; index < fileInputs.length; index += 1) {
        const fileInput = fileInputs[index];
        const filename = fileInput.value;
        const originalName = fileInput.dataset.originalName || filename;
        const row = getProgressRow(filename);
        const overallPercent = Math.round((index / fileInputs.length) * 100);

        updateOverallProgress(overallPercent, `Processing ${index + 1} of ${fileInputs.length}`);
        updateFileProgress(row, 18, "Processing");

        try {
          const formData = buildProcessPayload(filename);

          const response = await fetch("/process", {
            method: "POST",
            body: formData,
          });
          const data = await response.json();
          if (!response.ok || !data.ok) {
            throw new Error(data.error || "Video processing failed.");
          }

          results.push({ ...data, originalName });
          updateFileProgress(row, 100, "Complete", "bg-success");
        } catch (error) {
          failures.push(`${originalName}: ${error.message}`);
          updateFileProgress(row, 100, "Failed", "bg-danger");
        }
      }

      progressBar.style.width = "100%";
      progressBar.textContent = failures.length ? "Finished with errors" : "Complete";

      if (!results.length) {
        throw new Error(failures.join("\n") || "No videos were processed.");
      }

      const zipResponse = await fetch("/zip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filenames: results.map((result) => result.filename) }),
      });
      const zipData = await zipResponse.json();
      if (!zipResponse.ok || !zipData.ok) {
        throw new Error(zipData.error || "ZIP creation failed.");
      }

      const firstResult = results[0];
      previewVideo.src = firstResult.preview_url;
      downloadButton.href = firstResult.download_url;
      downloadButton.classList.remove("d-none");
      zipButton.href = zipData.zip_url;
      zipButton.classList.remove("d-none");
      renderOutputList(results);
      metadataBox.textContent = JSON.stringify(
        {
          processed: results.map((result) => result.metadata),
          failed: failures,
          zip: zipData.zip_filename,
        },
        null,
        2
      );
      youtubeTitle.value = firstResult.youtube_metadata.title;
      youtubeDescription.value = firstResult.youtube_metadata.description;
      youtubeKeywords.value = firstResult.youtube_metadata.keywords;
      resultPanel.classList.remove("d-none");
      resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });

      if (failures.length) {
        errorBox.textContent = failures.join("\n");
        errorBox.classList.remove("d-none");
      }
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("d-none");
      progressBar.style.width = "100%";
      progressBar.textContent = "Failed";
    } finally {
      processButton.disabled = false;
    }
  });

  document.querySelectorAll(".copy-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = button.dataset.copyTarget;
      const value = getCopyValue(target);
      if (!value) {
        return;
      }

      await copyText(value);
      const originalText = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = originalText;
      }, 1400);
    });
  });

  function getCopyValue(target) {
    if (target === "youtubeAll") {
      return [
        `Title: ${youtubeTitle.value}`,
        "",
        `Description:\n${youtubeDescription.value}`,
        "",
        `Keywords: ${youtubeKeywords.value}`,
      ].join("\n");
    }

    const field = document.getElementById(target);
    return field ? field.value : "";
  }

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "absolute";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }

  function resetBatchProgress() {
    document.querySelectorAll(".batch-progress-item").forEach((row) => {
      updateFileProgress(row, 0, "Queued");
    });
    updateOverallProgress(0, "Preparing");
  }

  function buildProcessPayload(filename) {
    const formData = new FormData();
    formData.append("filename", filename);
    appendField(formData, "output_format");
    appendField(formData, "category");
    appendField(formData, "trim_start");
    appendField(formData, "trim_end");
    appendField(formData, "title");
    appendField(formData, "text_position");
    appendField(formData, "logo_position");

    const muteAudio = document.getElementById("mute_audio");
    if (muteAudio && muteAudio.checked) {
      formData.append("mute_audio", "on");
    }

    appendFile(formData, "logo");
    appendFile(formData, "music");
    return formData;
  }

  function appendField(formData, fieldId) {
    const field = document.getElementById(fieldId);
    if (field) {
      formData.append(fieldId, field.value || "");
    }
  }

  function appendFile(formData, fieldId) {
    const field = document.getElementById(fieldId);
    if (field && field.files && field.files.length) {
      formData.append(fieldId, field.files[0]);
    }
  }

  function getProgressRow(filename) {
    return Array.from(document.querySelectorAll(".batch-progress-item")).find(
      (row) => row.dataset.progressFilename === filename
    );
  }

  function updateOverallProgress(percent, label) {
    progressBar.style.width = `${percent}%`;
    progressBar.textContent = label;
  }

  function updateFileProgress(row, percent, label, colorClass = "") {
    if (!row) {
      return;
    }

    const bar = row.querySelector(".progress-bar");
    const status = row.querySelector(".batch-status");
    bar.className = `progress-bar ${colorClass}`.trim();
    bar.style.width = `${percent}%`;
    bar.textContent = `${percent}%`;
    status.textContent = label;
  }

  function renderOutputList(results) {
    outputList.innerHTML = results
      .map(
        (result, index) => `
          <div class="output-list-item">
            <span>${escapeHtml(result.originalName)}</span>
            <a href="${result.download_url}" download>Download MP4 ${index + 1}</a>
          </div>
        `
      )
      .join("");
  }

  function escapeHtml(value) {
    return value.replace(/[&<>"']/g, (character) => {
      const entities = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      };
      return entities[character];
    });
  }
}
