export type Language = "vi" | "en";

export interface Translations {
  nav: {
    studio: string;
    history: string;
    tools: string;
    reprocess: string;
    rules: string;
    settings: string;
    license: string;
  };
  home: {
    eyebrow: string;
    title1: string;
    title2: string;
    description: string;
    convert: string;
    checking: string;
    step1: string;
    step2: string;
    step3: string;
    step4: string;
    workspace: string;
    jobs: string;
    completedToHistory: string;
    refresh: string;
    thName: string;
    thDuration: string;
    thStatus: string;
    thProgress: string;
    thCreated: string;
    thOutput: string;
    thActions: string;
    details: string;
    closeDetails: string;
    retry: string;
    continueTranslate: string;
    emptyTitle: string;
    emptyDesc: string;
    footer: string;
    resourceWarningTitle: string;
    existingWorkflows: string;
    queueWait: string;
    dismiss: string;
    queuedNotice: string;
    stoppingAfterTask: string;
    deletingWorkflow: string;
    chunksUnit: string;
  };
  statusLabels: Record<string, string>;
  settings: {
    eyebrow: string;
    title: string;
    description: string;
    langSection: string;
    langDesc: string;
    langVi: string;
    langEn: string;
    currentLangNote: string;
    ytSection: string;
    ytDesc: string;
    ytStep1: string;
    ytStep2: string;
    ytStep3: string;
    ytStep4: string;
    reconnect: string;
    connect: string;
    check: string;
    disconnect: string;
    lastChecked: string;
    profileLocation: string;
    processing: string;
    browserRequired: string;
    legacyCookieNotice: string;
    closeWindowNotice: string;
    ytSecurityNote1: string;
    ytSecurityNote2: string;
    ytStatusLabels: Record<string, string>;
    openNotice: string;
    checkNotice: string;
    disconnectNotice: string;
    loadError: string;
    updateError: string;
  };
  license: {
    eyebrow: string;
    title: string;
    machineId: string;
    copy: string;
    copied: string;
    copyPrompt: string;
    instructions: string;
    tokenType: string;
    activateFirst: string;
    renew: string;
    tokenLabel: string;
    verifyAndSave: string;
    verifying: string;
    savedNotice: string;
    saveFailed: string;
    cannotRead: string;
    expires: string;
    bannerLink: string;
    bannerFallback: string;
    licenseLabel: string;
  };
  history: {
    eyebrow: string;
    title: string;
    subtitle: string;
    searchPlaceholder: string;
    allStatuses: string;
    newest: string;
    oldest: string;
    refresh: string;
    thNumber: string;
    thSource: string;
    thCreated: string;
    thStatus: string;
    thProgress: string;
    thTotalTime: string;
    thOutputs: string;
    thActions: string;
    viewDownload: string;
    reprocess: string;
    delete: string;
    noResults: string;
    runs: string;
    page: string;
    prev: string;
    next: string;
    confirmDelete: string;
    staleOutputs: string;
    loadError: string;
    deleteError: string;
  };
  tools: {
    eyebrow: string;
    title: string;
    subtitle: string;
    inputFile: string;
    run: string;
    uploading: string;
    historyHeading: string;
    queued: string;
    uploadFailed: string;
  };
  reprocess: {
    title: string;
    description: string;
    workflowLabel: string;
    chooseWorkflow: string;
    restartFrom: string;
    reprocessButton: string;
    viewOutputs: string;
    queuedNotice: string;
    sendFailed: string;
  };
  rules: {
    eyebrow: string;
    title: string;
    description: string;
    lockedNotice: string;
    addRule: string;
    editRule: string;
    original: string;
    replacement: string;
    emptyPlaceholder: string;
    actions: string;
    edit: string;
    delete: string;
    save: string;
    saving: string;
    cancel: string;
    empty: string;
    loading: string;
    loadError: string;
    saveError: string;
  };
  workflowActions: {
    pause: string;
    resume: string;
    abort: string;
    confirmAbort: string;
    pauseNotice: string;
    resumeNotice: string;
    abortNotice: string;
    abortQueuedNotice: string;
    requestFailed: string;
  };
  voiceSelect: {
    label: string;
    placeholder: string;
    loading: string;
    play: string;
    stop: string;
    waitingIdle: string;
    building: string;
    failed: string;
    notCreated: string;
    previewNote: string;
    playError: string;
  };
  jobDetail: {
    heading: string;
    close: string;
    openInHistory: string;
    ready: string;
    noOutput: string;
    pendingDesc: string;
    closeView: string;
    view: string;
    download: string;
    transcriptLoading: string;
    transcriptEmpty: string;
    transcriptError: string;
    activeRequired: string;
  };
}

export const translations: Record<Language, Translations> = {
  vi: {
    nav: {
      studio: "Studio",
      history: "Lịch sử",
      tools: "Tools",
      reprocess: "Reprocess",
      rules: "Community Rules",
      settings: "Cài đặt",
      license: "License",
    },
    home: {
      eyebrow: "TIẾNG TRUNG → TIẾNG VIỆT",
      title1: "Tạo Audio Việt Nam",
      title2: "từ Video Audio Trung Quốc",
      description: "Chép lời, dịch tiếng Việt, thay thế từ theo rules của bạn và tạo giọng đọc. Theo dõi từng bước và tải kết quả ngay trong Studio.",
      convert: "Convert",
      checking: "Đang kiểm tra…",
      step1: "01 · Transcription",
      step2: "02 · Translation",
      step3: "03 · Moderation",
      step4: "04 · Vietnamese voice",
      workspace: "WORKSPACE",
      jobs: "Jobs",
      completedToHistory: "Workflow hoàn tất → Lịch sử",
      refresh: "↻ Làm mới",
      thName: "Name",
      thDuration: "Duration",
      thStatus: "Status",
      thProgress: "Progress",
      thCreated: "Created",
      thOutput: "Output",
      thActions: "Thao tác",
      details: "Chi tiết",
      closeDetails: "Đóng chi tiết",
      retry: "Thử lại ↻",
      continueTranslate: "Tiếp tục dịch và đọc →",
      emptyTitle: "Không có workflow đang xử lý",
      emptyDesc: "Workflow hoàn tất được lưu trong Lịch sử. Nhập URL YouTube để bắt đầu.",
      footer: "Audio Studio · Chinese to Vietnamese",
      resourceWarningTitle: "Chưa đủ tài nguyên dự phòng để chạy thêm cùng lúc",
      existingWorkflows: "workflow đang chạy hoặc chờ. Bộ kiểm tra không khởi động model.",
      queueWait: "Xếp hàng chờ",
      dismiss: "Để sau",
      queuedNotice: "Đã xếp hàng workflow. Các workflow được xử lý lần lượt; Auto sẽ chờ nếu chưa đủ RAM.",
      stoppingAfterTask: "Đang dừng sau task hiện tại",
      deletingWorkflow: "Đang hủy và xóa",
      chunksUnit: "đoạn",
    },
    statusLabels: {
      CANCELLED: "Đã dừng (phiên cũ)",
      PAUSED: "Đã dừng tạm",
      PARTIAL: "Một phần",
      DELETING: "Đang xóa",
      QUEUED: "Đang chờ",
      DOWNLOADING: "Đang tải audio",
      VAD: "Đang tách lời nói",
      TRANSCRIBING: "Đang nhận dạng",
      MERGING: "Đang ghép bản chép",
      COMPLETED: "Hoàn tất",
      FAILED: "Lỗi",
      TRANSCRIPTION_COMPLETED: "Đã chép tiếng Trung",
      TRANSLATING: "Đang dịch tiếng Việt",
      TRANSLATION_COMPLETED: "Đã dịch",
      MODERATING: "Đang thay thế từ",
      MODERATION_COMPLETED: "Đã duyệt bản dịch",
      TTS_GENERATING: "Đang tạo giọng Việt",
    },
    settings: {
      eyebrow: "SETTINGS",
      title: "Cài đặt hệ thống",
      description: "Cấu hình ngôn ngữ giao diện và kết nối YouTube cho Audio Studio.",
      langSection: "Ngôn ngữ giao diện",
      langDesc: "Chọn ngôn ngữ hiển thị. Thuật ngữ kỹ thuật, tên gọi, Studio và Audio luôn được giữ nguyên.",
      langVi: "Tiếng Việt (Mặc định)",
      langEn: "English",
      currentLangNote: "Giao diện đang sử dụng Tiếng Việt.",
      ytSection: "Kết nối YouTube",
      ytDesc: "Đăng nhập một lần trong profile riêng của Audio Studio. App tự lấy cookie mới cho mỗi lần tải; phiên đăng nhập được giữ khi cập nhật app.",
      ytStep1: "Đóng cửa sổ profile YouTube cũ đang báo lỗi, nếu có. Không cần xóa profile.",
      ytStep2: "Bấm Kết nối YouTube để mở Edge/Chrome bình thường, không điều khiển từ xa.",
      ytStep3: "Tự đăng nhập YouTube và xử lý xác minh Google nếu có.",
      ytStep4: "Đóng cửa sổ profile YouTube riêng đó, rồi quay lại đây bấm Kiểm tra kết nối.",
      reconnect: "Đăng nhập lại / Mở YouTube",
      connect: "Kết nối YouTube",
      check: "Kiểm tra kết nối",
      disconnect: "Ngừng sử dụng profile",
      lastChecked: "Lần kiểm tra gần nhất:",
      profileLocation: "Nơi lưu profile trên máy",
      processing: "Đang xử lý kết nối…",
      browserRequired: "Cài Microsoft Edge hoặc Google Chrome để dùng kết nối này.",
      legacyCookieNotice: "App đang dùng file cookie đã cấu hình. Khi kết nối profile, app sẽ ưu tiên phiên trong profile.",
      closeWindowNotice: "App không điều khiển cửa sổ đăng nhập. Đóng cửa sổ profile riêng trước khi mở lại hoặc kiểm tra phiên đã lưu.",
      ytSecurityNote1: "App chỉ kiểm tra phiên đã lưu; quyền truy cập từng video được YouTube xác nhận khi tải. Nếu YouTube hết hạn phiên hoặc yêu cầu xác minh, hãy dùng Đăng nhập lại. Cookie không được đưa vào bộ cài hay gửi cho Admin.",
      ytSecurityNote2: "Nếu Google vẫn báo trình duyệt không an toàn, hãy cập nhật Edge/Chrome và thử đăng nhập thủ công trong trình duyệt đó. App không tắt bảo mật, giả mạo trình duyệt hay tự vượt CAPTCHA/2FA.",
      ytStatusLabels: {
        NOT_CONNECTED: "Chưa kết nối",
        AWAITING_SIGN_IN: "Đang chờ đăng nhập",
        CLOSE_LOGIN_WINDOW: "Cần đóng cửa sổ profile YouTube trước",
        SESSION_SAVED: "Đã lưu phiên đăng nhập",
        SIGN_IN_REQUIRED: "Cần đăng nhập lại",
      },
      openNotice: "Cửa sổ YouTube bình thường đã mở. Đăng nhập thủ công, đóng cửa sổ đó rồi bấm Kiểm tra kết nối.",
      checkNotice: "Đã tìm thấy phiên đăng nhập. Những lần tải tiếp theo sẽ tự lấy cookie mới từ profile này.",
      disconnectNotice: "Đã ngừng dùng profile. Phiên đã lưu vẫn được giữ trên máy để kết nối lại.",
      loadError: "Không tải được kết nối YouTube.",
      updateError: "Không cập nhật được kết nối.",
    },
    license: {
      eyebrow: "LICENSE & RENEWAL",
      title: "License của máy này",
      machineId: "Machine ID",
      copy: "Copy",
      copied: "Đã copy Machine ID.",
      copyPrompt: "Hãy chọn và copy Machine ID.",
      instructions: "Gửi Machine ID cho Admin để nhận token kích hoạt dành riêng cho máy này. Nhập token gia hạn theo thứ tự Admin cấp.",
      tokenType: "Loại token",
      activateFirst: "Kích hoạt lần đầu",
      renew: "Gia hạn",
      tokenLabel: "Token",
      verifyAndSave: "Xác minh và lưu",
      verifying: "Đang xác minh…",
      savedNotice: "Đã lưu license an toàn trên máy này.",
      saveFailed: "Không nhập được license.",
      cannotRead: "Không đọc được trạng thái license.",
      expires: "Hết hạn",
      bannerLink: "Kích hoạt / Gia hạn",
      bannerFallback: " · Bạn vẫn có thể mở History và tải file đã tạo.",
      licenseLabel: "License:",
    },
    history: {
      eyebrow: "SAVED RESULTS",
      title: "History",
      subtitle: "Các kết quả đã lưu, sẵn sàng xem và tải xuống.",
      searchPlaceholder: "Số, tên hoặc nguồn…",
      allStatuses: "All statuses",
      newest: "Mới nhất trước",
      oldest: "Cũ nhất trước",
      refresh: "↻ Làm mới",
      thNumber: "Workflow #",
      thSource: "Source / Input",
      thCreated: "Created",
      thStatus: "Status",
      thProgress: "Progress",
      thTotalTime: "Total Time",
      thOutputs: "Outputs",
      thActions: "Thao tác",
      viewDownload: "Xem / Tải",
      reprocess: "Reprocess",
      delete: "Xóa",
      noResults: "Chưa có kết quả phù hợp.",
      runs: "lần chạy",
      page: "Trang",
      prev: "← Trước",
      next: "Sau →",
      confirmDelete: "Xóa run và toàn bộ file liên quan?\nThao tác này không thể hoàn tác.",
      staleOutputs: " · STALE outputs",
      loadError: "Không tải được history.",
      deleteError: "Không xóa được run.",
    },
    tools: {
      eyebrow: "STANDALONE TOOLS",
      title: "Sử dụng tool đơn",
      subtitle: "Dùng lại các adapter của workflow. Audio tối đa 2 GiB; UTF-8 TXT/MD/JSONL tối đa 64 MiB, mỗi dòng tối đa 64 KiB.",
      inputFile: "Input file",
      run: "Run",
      uploading: "Đang upload…",
      historyHeading: "Tool History",
      queued: "Tool run đã được thêm vào hàng đợi.",
      uploadFailed: "Upload thất bại.",
    },
    reprocess: {
      title: "Reprocess workflow",
      description: "Giữ kết quả trước bước được chọn. Tạo lại bước này và toàn bộ bước phía sau với cùng Workflow #.",
      workflowLabel: "Workflow",
      chooseWorkflow: "Chọn workflow",
      restartFrom: "Restart From",
      reprocessButton: "Reprocess",
      viewOutputs: "View outputs →",
      queuedNotice: "Đã xếp hàng reprocess; các output downstream hiện là STALE.",
      sendFailed: "Không gửi được reprocess.",
    },
    rules: {
      eyebrow: "BEFORE THE VOICE",
      title: "Community Moderation Rules",
      description: "Thay từ và cụm từ trong bản dịch trước khi tạo giọng đọc. Mỗi job giữ danh sách rules tại thời điểm bắt đầu moderation.",
      lockedNotice: "Replacement rules are locked while moderation is running.",
      addRule: "Add Rule",
      editRule: "Edit Rule",
      original: "Original",
      replacement: "Replacement",
      emptyPlaceholder: "Để trống",
      actions: "Actions",
      edit: "Edit",
      delete: "Delete",
      save: "Save",
      saving: "Saving…",
      cancel: "Cancel",
      empty: "Chưa có rule. Bản dịch sẽ được giữ nguyên, chỉ chuẩn hóa Unicode.",
      loading: "Đang tải rules…",
      loadError: "Không tải được rules.",
      saveError: "Không lưu được rule.",
    },
    workflowActions: {
      pause: "Dừng giai đoạn",
      resume: "Tiếp tục giai đoạn",
      abort: "Hủy và xóa workflow",
      confirmAbort: "Hủy workflow và xóa toàn bộ audio, checkpoint, kết quả liên quan?\nKhông thể hoàn tác. Model, giọng mẫu và các workflow khác được giữ nguyên.",
      pauseNotice: "Đã yêu cầu dừng sau task hiện tại và lưu checkpoint.",
      resumeNotice: "Đã xếp hàng tiếp tục từ checkpoint.",
      abortNotice: "Đã hủy và xóa dữ liệu workflow.",
      abortQueuedNotice: "Đã yêu cầu hủy; dữ liệu sẽ được xóa sau khi worker dừng.",
      requestFailed: "Không gửi được yêu cầu.",
    },
    voiceSelect: {
      label: "Vietnamese Voice",
      placeholder: "Chọn giọng",
      loading: "Đang tải giọng…",
      play: "Nghe thử",
      stop: "Dừng",
      waitingIdle: "Mẫu giọng sẽ được tạo sau khi workflow đang chạy hoàn tất.",
      building: "Đang tạo mẫu giọng một lần…",
      failed: "Tạo mẫu giọng chưa thành công.",
      notCreated: "Mẫu giọng chưa được tạo.",
      previewNote: "Bấm nghe thử chỉ phát file lưu sẵn, không chạy model.",
      playError: "Không phát được mẫu giọng. Vui lòng thử lại.",
    },
    jobDetail: {
      heading: "JOB DETAIL",
      close: "Đóng",
      openInHistory: "Mở trong History →",
      ready: "SẴN SÀNG",
      noOutput: "CHƯA CÓ OUTPUT",
      pendingDesc: "Sẽ xuất hiện khi bước xử lý hoàn tất.",
      closeView: "Đóng xem",
      view: "Xem",
      download: "Tải",
      transcriptLoading: "Đang tải bản xem trước…",
      transcriptEmpty: "Không có lời nói trong bản chép.",
      transcriptError: "Không đọc được transcript.",
      activeRequired: "License cần ACTIVE để phát audio.",
    },
  },
  en: {
    nav: {
      studio: "Studio",
      history: "History",
      tools: "Tools",
      reprocess: "Reprocess",
      rules: "Community Rules",
      settings: "Settings",
      license: "License",
    },
    home: {
      eyebrow: "CHINESE → VIETNAMESE",
      title1: "Create Vietnamese Audio",
      title2: "from Chinese Video Audio",
      description: "Transcribe, translate to Vietnamese, replace words with your rules and generate voice. Track each step and download results right in Studio.",
      convert: "Convert",
      checking: "Checking…",
      step1: "01 · Transcription",
      step2: "02 · Translation",
      step3: "03 · Moderation",
      step4: "04 · Vietnamese voice",
      workspace: "WORKSPACE",
      jobs: "Jobs",
      completedToHistory: "Completed workflows → History",
      refresh: "↻ Refresh",
      thName: "Name",
      thDuration: "Duration",
      thStatus: "Status",
      thProgress: "Progress",
      thCreated: "Created",
      thOutput: "Output",
      thActions: "Actions",
      details: "Details",
      closeDetails: "Close details",
      retry: "Retry ↻",
      continueTranslate: "Continue translate & TTS →",
      emptyTitle: "No active workflows",
      emptyDesc: "Completed workflows are saved in History. Enter a YouTube URL to get started.",
      footer: "Audio Studio · Chinese to Vietnamese",
      resourceWarningTitle: "Insufficient headroom to run another workflow concurrently",
      existingWorkflows: "workflows running or queued. Preflight check did not launch model.",
      queueWait: "Queue workflow",
      dismiss: "Dismiss",
      queuedNotice: "Workflow queued. Workflows are processed sequentially; Auto will wait if RAM is insufficient.",
      stoppingAfterTask: "Stopping after current task",
      deletingWorkflow: "Canceling and deleting",
      chunksUnit: "chunks",
    },
    statusLabels: {
      CANCELLED: "Stopped (old session)",
      PAUSED: "Paused",
      PARTIAL: "Partial",
      DELETING: "Deleting",
      QUEUED: "Queued",
      DOWNLOADING: "Downloading audio",
      VAD: "Detecting speech (VAD)",
      TRANSCRIBING: "Transcribing",
      MERGING: "Merging transcript",
      COMPLETED: "Completed",
      FAILED: "Failed",
      TRANSCRIPTION_COMPLETED: "Chinese transcribed",
      TRANSLATING: "Translating to Vietnamese",
      TRANSLATION_COMPLETED: "Translated",
      MODERATING: "Moderating text",
      MODERATION_COMPLETED: "Translation approved",
      TTS_GENERATING: "Generating Vietnamese voice",
    },
    settings: {
      eyebrow: "SETTINGS",
      title: "Settings",
      description: "Configure interface language and YouTube connection for Audio Studio.",
      langSection: "Interface Language",
      langDesc: "Choose display language. Technical terms, proper names, Studio, and Audio are preserved.",
      langVi: "Tiếng Việt",
      langEn: "English",
      currentLangNote: "Interface is currently displayed in English.",
      ytSection: "YouTube Connection",
      ytDesc: "Sign in once inside Audio Studio's dedicated profile. The app automatically fetches fresh cookies for each download; sessions are preserved across app updates.",
      ytStep1: "Close any old YouTube profile window reporting errors, if open. No need to delete profile.",
      ytStep2: "Click Connect YouTube to launch Edge/Chrome normally without remote automation.",
      ytStep3: "Manually sign in to YouTube and complete any Google verification steps.",
      ytStep4: "Close the dedicated YouTube window, then return here and click Check connection.",
      reconnect: "Sign in again / Open YouTube",
      connect: "Connect YouTube",
      check: "Check connection",
      disconnect: "Stop using profile",
      lastChecked: "Last checked:",
      profileLocation: "Profile storage location on machine",
      processing: "Processing connection…",
      browserRequired: "Install Microsoft Edge or Google Chrome to use this connection.",
      legacyCookieNotice: "App is currently using configured cookie file. When a profile is connected, the profile session will be prioritized.",
      closeWindowNotice: "App does not automate login windows. Close the dedicated profile window before reopening or checking saved sessions.",
      ytSecurityNote1: "App only inspects saved sessions; video permissions are verified by YouTube on download. If session expires or requests verification, use Sign in again. Cookies are never bundled into installer or sent to Admin.",
      ytSecurityNote2: "If Google reports browser unsafe, update Edge/Chrome and sign in manually in that browser. App does not disable security, spoof browsers, or bypass CAPTCHA/2FA.",
      ytStatusLabels: {
        NOT_CONNECTED: "Not connected",
        AWAITING_SIGN_IN: "Awaiting sign-in",
        CLOSE_LOGIN_WINDOW: "Close YouTube profile window first",
        SESSION_SAVED: "Session saved",
        SIGN_IN_REQUIRED: "Sign-in required",
      },
      openNotice: "YouTube window opened. Sign in manually, close that window, then click Check connection.",
      checkNotice: "Saved session detected. Subsequent downloads will automatically use fresh cookies from this profile.",
      disconnectNotice: "Stopped using profile. Saved session remains on machine for future reconnection.",
      loadError: "Failed to load YouTube connection.",
      updateError: "Failed to update connection.",
    },
    license: {
      eyebrow: "LICENSE & RENEWAL",
      title: "License for this machine",
      machineId: "Machine ID",
      copy: "Copy",
      copied: "Machine ID copied.",
      copyPrompt: "Please select and copy Machine ID.",
      instructions: "Send Machine ID to Admin to receive an activation token for this machine. Enter renewal tokens in the order issued by Admin.",
      tokenType: "Token type",
      activateFirst: "Initial activation",
      renew: "Renewal",
      tokenLabel: "Token",
      verifyAndSave: "Verify and save",
      verifying: "Verifying…",
      savedNotice: "License saved securely on this machine.",
      saveFailed: "Failed to apply license.",
      cannotRead: "Cannot read license status.",
      expires: "Expires",
      bannerLink: "Activate / Renew",
      bannerFallback: " · You can still open History and download completed files.",
      licenseLabel: "License:",
    },
    history: {
      eyebrow: "SAVED RESULTS",
      title: "History",
      subtitle: "Saved results, ready to view and download.",
      searchPlaceholder: "Number, name or source…",
      allStatuses: "All statuses",
      newest: "Newest first",
      oldest: "Oldest first",
      refresh: "↻ Refresh",
      thNumber: "Workflow #",
      thSource: "Source / Input",
      thCreated: "Created",
      thStatus: "Status",
      thProgress: "Progress",
      thTotalTime: "Total Time",
      thOutputs: "Outputs",
      thActions: "Actions",
      viewDownload: "View / Download",
      reprocess: "Reprocess",
      delete: "Delete",
      noResults: "No matching results found.",
      runs: "runs",
      page: "Page",
      prev: "← Previous",
      next: "Next →",
      confirmDelete: "Delete run and all related files?\nThis action cannot be undone.",
      staleOutputs: " · STALE outputs",
      loadError: "Failed to load history.",
      deleteError: "Failed to delete run.",
    },
    tools: {
      eyebrow: "STANDALONE TOOLS",
      title: "One task, one step.",
      subtitle: "Reuse workflow adapters. Audio up to 2 GiB; UTF-8 TXT/MD/JSONL up to 64 MiB, max 64 KiB per line.",
      inputFile: "Input file",
      run: "Run",
      uploading: "Uploading…",
      historyHeading: "Tool History",
      queued: "Tool run queued successfully.",
      uploadFailed: "Upload failed.",
    },
    reprocess: {
      title: "Reprocess workflow",
      description: "Keep results prior to selected step. Regenerate this step and all downstream steps under the same Workflow #.",
      workflowLabel: "Workflow",
      chooseWorkflow: "Choose workflow",
      restartFrom: "Restart From",
      reprocessButton: "Reprocess",
      viewOutputs: "View outputs →",
      queuedNotice: "Reprocess queued; downstream outputs are now marked STALE.",
      sendFailed: "Failed to submit reprocess request.",
    },
    rules: {
      eyebrow: "BEFORE THE VOICE",
      title: "Community Moderation Rules",
      description: "Replace words and phrases in translation before generating voice. Each job keeps the rules snapshot at the moment moderation starts.",
      lockedNotice: "Replacement rules are locked while moderation is running.",
      addRule: "Add Rule",
      editRule: "Edit Rule",
      original: "Original",
      replacement: "Replacement",
      emptyPlaceholder: "Empty",
      actions: "Actions",
      edit: "Edit",
      delete: "Delete",
      save: "Save",
      saving: "Saving…",
      cancel: "Cancel",
      empty: "No rules yet. Translation will be kept as-is, with Unicode normalization.",
      loading: "Loading rules…",
      loadError: "Failed to load rules.",
      saveError: "Failed to save rule.",
    },
    workflowActions: {
      pause: "Pause stage",
      resume: "Resume stage",
      abort: "Abort & delete workflow",
      confirmAbort: "Abort workflow and delete all audio, checkpoints, and related results?\nCannot be undone. Models, voice samples, and other workflows remain intact.",
      pauseNotice: "Pause requested after current task; checkpoint will be saved.",
      resumeNotice: "Queued to resume from checkpoint.",
      abortNotice: "Workflow data aborted and deleted.",
      abortQueuedNotice: "Abort requested; data will be deleted once worker stops.",
      requestFailed: "Failed to submit request.",
    },
    voiceSelect: {
      label: "Vietnamese Voice",
      placeholder: "Choose voice",
      loading: "Loading voices…",
      play: "Preview",
      stop: "Stop",
      waitingIdle: "Voice sample will be generated after the running workflow completes.",
      building: "Generating one-time voice sample…",
      failed: "Voice sample generation failed.",
      notCreated: "Voice sample not yet generated.",
      previewNote: "Preview only plays saved audio files, without running models.",
      playError: "Cannot play voice preview. Please try again.",
    },
    jobDetail: {
      heading: "JOB DETAIL",
      close: "Close",
      openInHistory: "Open in History →",
      ready: "READY",
      noOutput: "NO OUTPUT",
      pendingDesc: "Will appear once step finishes.",
      closeView: "Close view",
      view: "View",
      download: "Download",
      transcriptLoading: "Loading preview…",
      transcriptEmpty: "No speech found in transcript.",
      transcriptError: "Failed to load transcript.",
      activeRequired: "License must be ACTIVE to play audio.",
    },
  },
};
