"""Short, stable error IDs: the only thing a person sees of a failure (a Vietnamese sentence, what to do, and an ID such as T101).

The raw detail (the English text of a library, an HTTP status, a path) goes to the run's errors.jsonl and never to the screen, so a
person can read the ID out or photograph it and the owner looks it up in the list of IDs. An ID is never renumbered or reused.

Groups: G licence and protection, T download and YouTube, C transcription, D translation, K moderation, V voice, P subtitles, H video,
M downloaded data, S the computer, U app updates, X general.
"""


class AppError(Exception):
    """A failure that already knows its ID. `detail` is the raw text for the log only."""
    def __init__(self, error_id, detail=''):
        super().__init__(f'{error_id}: {detail}' if detail else error_id)
        self.error_id, self.detail = error_id, str(detail or '')


# ID: (what happened, what to do). Both are shown to the person, in Vietnamese.
ERRORS = {
    'G101': ('Ứng dụng chưa được kích hoạt.', 'Mở trang Giấy phép, gửi Mã máy cho người bán rồi nhập mã kích hoạt.'),
    'G102': ('Giấy phép đã hết hạn.', 'Gia hạn ở trang Giấy phép. Kết quả đã làm vẫn xem và tải được.'),
    'G103': ('Đồng hồ máy không đúng.', 'Chỉnh lại ngày giờ Windows rồi mở lại ứng dụng.'),
    'G104': ('Chưa xác nhận được thời gian.', 'Kiểm tra Internet rồi thử lại.'),
    'G105': ('Giấy phép này không dùng cho máy này.', 'Liên hệ người bán.'),
    'G106': ('Mã kích hoạt không hợp lệ.', 'Kiểm tra đã nhập đủ và đúng mã.'),
    'G107': ('Cần nhập mã gia hạn tiếp theo.', 'Nhập mã gia hạn theo đúng thứ tự.'),
    'G108': ('Cần kết nối Internet để xác nhận lại quyền sử dụng.', 'Kết nối mạng rồi bấm Kiểm tra lại.'),
    'G109': ('Phiên bản này đã ngừng hỗ trợ.', 'Cập nhật ứng dụng ở Cài đặt → Cập nhật ứng dụng.'),
    'G110': ('Giấy phép đã bị thu hồi.', 'Liên hệ người bán.'),
    'G111': ('Dịch vụ Genius chưa chấp nhận giấy phép này.', 'Liên hệ người bán.'),
    'G120': ('Ứng dụng cần được cài lại.', 'Cài lại bản mới nhất (dữ liệu của bạn được giữ).'),
    'G121': ('Ứng dụng cần được cài lại.', 'Cài lại bản mới nhất (dữ liệu của bạn được giữ).'),
    'G122': ('Ứng dụng cần được cài lại.', 'Cài lại bản mới nhất (dữ liệu của bạn được giữ).'),
    'G123': ('Cần xác nhận lại quyền sử dụng.', 'Mở lại ứng dụng khi có Internet.'),
    'G124': ('Cần xác nhận lại quyền sử dụng.', 'Mở lại ứng dụng khi có Internet.'),
    'T101': ('YouTube yêu cầu đăng nhập lại.', 'Vào Cài đặt → Kết nối YouTube, đăng nhập rồi bấm Thử lại.'),
    'T102': ('YouTube yêu cầu đăng nhập lại.', 'Vào Cài đặt → Kết nối YouTube, đăng nhập rồi bấm Thử lại.'),
    'T103': ('YouTube đang tạm giới hạn tải.', 'Chờ vài phút rồi thử lại, hoặc dùng tệp âm thanh.'),
    'T104': ('Không tải được âm thanh từ liên kết này.', 'Kiểm tra liên kết còn xem được, hoặc dùng tệp âm thanh.'),
    'T105': ('Không tải được âm thanh từ liên kết này.', 'Kiểm tra liên kết còn xem được, hoặc dùng tệp âm thanh.'),
    'T106': ('Không lấy được thông tin video.', 'Kiểm tra liên kết rồi thử lại.'),
    'T107': ('Không tải được âm thanh từ liên kết này.', 'Thử lại; nếu vẫn lỗi hãy gửi mã lỗi này.'),
    'T108': ('Tệp âm thanh đã nạp không còn trong quy trình.', 'Tạo quy trình mới và chọn lại tệp.'),
    'T109': ('Quy trình này không có liên kết YouTube.', 'Tạo quy trình mới.'),
    'T110': ('Định dạng âm thanh chưa được hỗ trợ.', 'Dùng tệp WAV, MP3, M4A, FLAC, OGG hoặc AAC.'),
    'T111': ('Tệp không có âm thanh.', 'Chọn tệp khác.'),
    'T120': ('Không đọc được đăng nhập YouTube.', 'Đóng cửa sổ kết nối rồi đăng nhập lại.'),
    'T121': ('Cửa sổ đăng nhập YouTube không phản hồi.', 'Đóng cửa sổ đó rồi thử lại.'),
    'T122': ('Cần cài Microsoft Edge hoặc Google Chrome.', 'Cài một trong hai rồi mở lại Kết nối YouTube.'),
    'T123': ('Không mở được cửa sổ đăng nhập YouTube.', 'Đóng cửa sổ đó rồi thử lại.'),
    'T124': ('Cửa sổ YouTube cũ đang mở ở chế độ khác.', 'Đóng cửa sổ YouTube riêng của ứng dụng rồi bấm Mở YouTube lại.'),
    'T125': ('Hãy đăng nhập xong và đóng cửa sổ YouTube trước.', 'Sau đó bấm Kiểm tra kết nối.'),
    'T126': ('YouTube cần đăng nhập.', 'Vào Cài đặt → Kết nối YouTube, đăng nhập rồi bấm Kiểm tra kết nối.'),
    'T127': ('Hãy kết nối YouTube trước khi kiểm tra.', 'Bấm Kết nối YouTube và đăng nhập.'),
    'T130': ('Tệp đăng nhập YouTube cũ không dùng được.', 'Dùng Cài đặt → Kết nối YouTube thay cho tệp này.'),
    'T131': ('Tệp đăng nhập YouTube cũ không có nội dung.', 'Dùng Cài đặt → Kết nối YouTube thay cho tệp này.'),
    'T132': ('Không tìm thấy tệp đăng nhập YouTube cũ.', 'Dùng Cài đặt → Kết nối YouTube thay cho tệp này.'),
    'T133': ('Đã cập nhật bộ tải YouTube.', 'Bấm Thử lại.'),
    'C101': ('Không đọc được âm thanh của tệp này.', 'Thử tệp khác hoặc tải lại.'),
    'C102': ('Không đọc được âm thanh của tệp này.', 'Thử tệp khác hoặc tải lại.'),
    'C103': ('Âm thanh bị ngắt sớm hơn dự kiến.', 'Tải lại tệp rồi thử lại.'),
    'C104': ('Một đoạn âm thanh trống.', 'Thử lại; nếu vẫn lỗi hãy gửi mã lỗi này.'),
    'C110': ('Không tải được dữ liệu cho lần dùng đầu.', 'Kiểm tra mạng rồi bấm Thử lại; phần đã tải được giữ lại.'),
    'C111': ('Dữ liệu cho lần dùng đầu tải chưa đủ.', 'Bấm Thử lại để tải tiếp.'),
    'D101': ('Dịch chưa hoàn tất.', 'Bấm Thử lại.'),
    'D110': ('Không kết nối được dịch vụ Genius.', 'Kiểm tra mạng rồi bấm Tiếp tục.'),
    'D111': ('Đã đến hạn mức sử dụng Genius.', 'Thanh toán rồi bấm Tiếp tục.'),
    'D112': ('Chưa dùng được Genius lúc này.', 'Liên hệ người bán.'),
    'K101': ('Từ gốc phải có nội dung.', 'Nhập từ gốc rồi lưu lại.'),
    'K102': ('Nội dung quá dài.', 'Từ gốc tối đa 1.000 ký tự, từ thay thế tối đa 10.000 ký tự.'),
    'K103': ('Từ gốc đã có trong danh sách.', 'Sửa quy tắc đã có thay vì thêm mới.'),
    'K104': ('Không tìm thấy quy tắc.', 'Tải lại danh sách rồi thử lại.'),
    'V101': ('Không tìm thấy giọng đọc.', 'Tạo lại giọng của quy trình này trước.'),
    'V102': ('Chưa tải được thư viện giọng.', 'Kiểm tra mạng và giấy phép; ứng dụng tự thử lại.'),
    'V103': ('Thiếu thành phần tạo giọng.', 'Cài lại ứng dụng.'),
    'V104': ('Không phát được giọng mẫu.', 'Thử lại.'),
    'P101': ('Không tạo được phụ đề từ giọng này.', 'Tạo lại bước Tạo giọng rồi chạy lại Phụ đề.'),
    'H101': ('Không tìm thấy video đã chọn.', 'Đưa tệp về chỗ cũ, hoặc chọn lại video ở Tạo lại → Ghép video.'),
    'H102': ('Không đọc được video đã chọn.', 'Mở thử bằng trình phát video của Windows; bỏ tệp lỗi rồi chọn lại video.'),
    'H103': ('Không còn video đã ghép để gắn phụ đề.', 'Tạo lại bước Ghép video, rồi chạy lại Gắn phụ đề.'),
    'H104': ('Không ghép được video.', 'Kiểm tra video còn nguyên rồi thử lại.'),
    'H105': ('Không gắn được phụ đề vào video.', 'Thử lại; nếu vẫn lỗi hãy gửi mã lỗi này.'),
    'M101': ('Chưa có mô hình dịch trên máy.', 'Vào Cài đặt để tải (cần Internet).'),
    'M102': ('Cần kích hoạt giấy phép còn hạn trước khi tải.', 'Kích hoạt ở trang Giấy phép.'),
    'M103': ('Chưa tải được lúc này.', 'Liên hệ người bán.'),
    'M104': ('Đã tải quá số lần cho phép trong ngày.', 'Thử lại vào ngày mai.'),
    'M105': ('Hiện chưa cho tải.', 'Thử lại sau.'),
    'M106': ('Mất kết nối mạng.', 'Bấm Thử lại để tải tiếp từ chỗ đang dở.'),
    'M107': ('Tệp tải về chưa đúng, đã xóa.', 'Bấm Thử lại.'),
    'M108': ('Tải chưa đủ dung lượng.', 'Bấm Thử lại để tải tiếp.'),
    'M109': ('Tải không thành công.', 'Bấm Thử lại.'),
    'S101': ('Ổ đĩa không còn đủ chỗ.', 'Giải phóng dung lượng rồi bấm Thử lại; kết quả đã làm được giữ.'),
    'S102': ('Không ghi được dữ liệu, hoặc tệp đang được chương trình khác mở.', 'Đóng chương trình đó rồi thử lại.'),
    'S103': ('Không tìm thấy tệp hoặc thư mục cần dùng.', 'Kiểm tra tệp còn ở chỗ cũ rồi thử lại.'),
    'S104': ('Bản cài bị thiếu tệp.', 'Cài lại ứng dụng (dữ liệu của bạn được giữ).'),
    'S105': ('Thiếu thành phần xử lý âm thanh và video.', 'Cài lại ứng dụng.'),
    'S106': ('Cấu hình không hợp lệ.', 'Liên hệ người bán kèm mã lỗi này.'),
    'S110': ('Card đồ họa không đủ bộ nhớ.', 'Đóng ứng dụng nặng rồi thử lại, hoặc chọn xử lý bằng CPU ở Cài đặt.'),
    'S111': ('Card đồ họa chưa dùng được cho tính năng này.', 'Chọn xử lý bằng CPU ở Cài đặt.'),
    'S120': ('Máy chưa đủ bộ nhớ trống nên đã tạm dừng.', 'Đóng bớt ứng dụng rồi bấm Tiếp tục.'),
    'S121': ('Chưa kiểm tra được tài nguyên máy.', 'Thử lại.'),
    'U101': ('Chưa kiểm tra được bản mới.', 'Cần Internet và giấy phép đang hoạt động.'),
    'U102': ('Tải bản cập nhật chưa thành công.', 'Bấm Thử lại.'),
    'U103': ('Liên kết tải đã hết hạn.', 'Bấm Kiểm tra cập nhật rồi tải lại.'),
    'U104': ('Chưa dùng được cập nhật lúc này.', 'Liên hệ người bán.'),
    'U105': ('Đang có quy trình chạy.', 'Hãy chờ hoặc xác nhận tạm dừng.'),
    'U106': ('Cập nhật không thành công, đã quay về bản trước.', 'Thử lại sau; nếu lặp lại hãy gửi mã lỗi này.'),
    'U107': ('Chưa có bản tải sẵn để cập nhật.', 'Bấm Tải và cập nhật.'),
    'X900': ('Có sự cố khi xử lý.', 'Bấm Thử lại; nếu vẫn lỗi hãy gửi mã lỗi này và số quy trình.'),
    'X901': ('Không gửi được yêu cầu.', 'Thử lại sau ít phút.'),
}

# The code the rest of the program already uses -> its ID.
CODE_IDS = {
    'UNACTIVATED': 'G101', 'EXPIRED': 'G102', 'CLOCK_ROLLBACK': 'G103', 'TRUSTED_TIME_UNAVAILABLE': 'G104', 'WRONG_MACHINE': 'G105',
    'INVALID': 'G106', 'RENEWAL_REQUIRED': 'G107', 'LEASE_OFFLINE': 'G108', 'VERSION_RETIRED': 'G109', 'LICENSE_REVOKED': 'G110',
    'LICENSE_REJECTED': 'G111', 'SECURITY_SERVICE_UNAVAILABLE': 'G120', 'INTEGRITY_FAILURE': 'G121', 'UNTRUSTED_BINARY': 'G122',
    'SECURE_STATE_INVALID': 'G123', 'LEASE_REQUIRED': 'G124',
    'YOUTUBE_AUTH': 'T101', 'RATE_LIMIT': 'T103',
    'GATEWAY_UNAVAILABLE': 'D110', 'CREDIT_LIMIT': 'D111',
    'VOICE_MISSING': 'V101', 'VAULT_UNCONFIGURED': 'V102',
    'SUBTITLE_FAILED': 'P101',
    'VIDEO_MISSING': 'H101', 'VIDEO_UNREADABLE': 'H102', 'VIDEO_RESULT_MISSING': 'H103',
    'MODEL_MISSING': 'M101', 'LICENSE_REQUIRED': 'M102', 'GATEWAY_NOT_CONFIGURED': 'M103', 'MODEL_LINK_LIMIT': 'M104',
    'MODEL_DOWNLOAD_DISABLED': 'M105', 'OFFLINE': 'M106', 'CHECKSUM_MISMATCH': 'M107', 'INCOMPLETE': 'M108', 'MODEL_DOWNLOAD_FAILED': 'M109',
    'DISK_FULL': 'S101', 'FILE_PERMISSION': 'S102', 'PATH_MISSING': 'S103', 'DEPENDENCY_MISSING': 'S104', 'FFMPEG_MISSING': 'S105',
    'ENV_CONFIG': 'S106', 'CUDA_OOM': 'S110', 'CUDA_CONFIG': 'S111',
}


def known(error_id):
    return error_id if error_id in ERRORS else 'X900'


def message(error_id):
    """What the person reads: what happened, what to do, and the ID."""
    what, todo = ERRORS[known(error_id)]
    return f'{what} {todo} Mã lỗi: {known(error_id)}.'


def parts(error_id):
    what, todo = ERRORS[known(error_id)]
    return {'id': known(error_id), 'message': what, 'hint': todo}
