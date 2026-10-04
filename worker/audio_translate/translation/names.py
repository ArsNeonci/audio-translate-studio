"""Per-job person-name glossary with Sino-Vietnamese (Hán-Việt) readings.

Hy-MT2 transliterates Chinese names inconsistently (宋轩 -> Song Xuan / Sông Xuân /
Sung Huan) and cannot produce Hán-Việt on request, but it follows a terminology
list reliably. Names are detected from the transcript once per job and stored in
`working/name-glossary.json`, which users may edit before Continue/Reprocess.

Readings come from curated tables of common surnames and given-name characters.
Unihan `kVietnamese` mixes Nôm readings (徐 -> chờ, 强 -> càng), so it is not used
directly. A name with any character outside the tables is skipped instead of guessed.
"""
from collections import Counter

COMPOUND_SURNAMES = {
    '欧阳': 'Âu Dương', '司马': 'Tư Mã', '诸葛': 'Gia Cát', '上官': 'Thượng Quan', '东方': 'Đông Phương',
    '慕容': 'Mộ Dung', '令狐': 'Lệnh Hồ', '皇甫': 'Hoàng Phủ', '夏侯': 'Hạ Hầu', '尉迟': 'Uất Trì',
    '公孙': 'Công Tôn', '长孙': 'Trưởng Tôn', '宇文': 'Vũ Văn', '司徒': 'Tư Đồ', '南宫': 'Nam Cung',
    '端木': 'Đoan Mộc', '独孤': 'Độc Cô', '西门': 'Tây Môn', '轩辕': 'Hiên Viên',
}

SURNAMES = {
    '王': 'Vương', '李': 'Lý', '张': 'Trương', '刘': 'Lưu', '陈': 'Trần', '杨': 'Dương', '黄': 'Hoàng',
    '赵': 'Triệu', '吴': 'Ngô', '周': 'Chu', '徐': 'Từ', '孙': 'Tôn', '马': 'Mã', '朱': 'Chu', '胡': 'Hồ',
    '郭': 'Quách', '何': 'Hà', '高': 'Cao', '林': 'Lâm', '罗': 'La', '郑': 'Trịnh', '梁': 'Lương',
    '谢': 'Tạ', '宋': 'Tống', '唐': 'Đường', '许': 'Hứa', '韩': 'Hàn', '冯': 'Phùng', '邓': 'Đặng',
    '曹': 'Tào', '彭': 'Bành', '曾': 'Tằng', '肖': 'Tiêu', '萧': 'Tiêu', '田': 'Điền', '董': 'Đổng',
    '袁': 'Viên', '潘': 'Phan', '于': 'Vu', '蒋': 'Tưởng', '蔡': 'Thái', '余': 'Dư', '杜': 'Đỗ',
    '叶': 'Diệp', '程': 'Trình', '苏': 'Tô', '魏': 'Ngụy', '吕': 'Lã', '丁': 'Đinh', '任': 'Nhậm',
    '沈': 'Thẩm', '姚': 'Diêu', '卢': 'Lư', '姜': 'Khương', '崔': 'Thôi', '钟': 'Chung', '谭': 'Đàm',
    '陆': 'Lục', '汪': 'Uông', '范': 'Phạm', '金': 'Kim', '石': 'Thạch', '廖': 'Liêu', '贾': 'Giả',
    '夏': 'Hạ', '韦': 'Vi', '傅': 'Phó', '方': 'Phương', '白': 'Bạch', '邹': 'Trâu', '孟': 'Mạnh',
    '熊': 'Hùng', '秦': 'Tần', '邱': 'Khâu', '江': 'Giang', '尹': 'Doãn', '薛': 'Tiết', '闫': 'Diêm',
    '阎': 'Diêm', '段': 'Đoàn', '雷': 'Lôi', '侯': 'Hầu', '龙': 'Long', '史': 'Sử', '陶': 'Đào',
    '黎': 'Lê', '贺': 'Hạ', '顾': 'Cố', '毛': 'Mao', '郝': 'Hác', '龚': 'Cung', '邵': 'Thiệu',
    '万': 'Vạn', '钱': 'Tiền', '严': 'Nghiêm', '武': 'Vũ', '戴': 'Đái', '莫': 'Mạc', '孔': 'Khổng',
    '向': 'Hướng', '汤': 'Thang', '穆': 'Mục', '常': 'Thường', '温': 'Ôn', '康': 'Khang', '施': 'Thi',
    '文': 'Văn', '牛': 'Ngưu', '樊': 'Phàn', '葛': 'Cát', '邢': 'Hình', '安': 'An', '齐': 'Tề',
    '易': 'Dịch', '乔': 'Kiều', '伍': 'Ngũ', '庞': 'Bàng', '颜': 'Nhan', '倪': 'Nghê', '庄': 'Trang',
    '聂': 'Nhiếp', '章': 'Chương', '鲁': 'Lỗ', '岳': 'Nhạc', '翟': 'Địch', '殷': 'Ân', '詹': 'Chiêm',
    '申': 'Thân', '欧': 'Âu', '耿': 'Cảnh', '关': 'Quan', '兰': 'Lan', '焦': 'Tiêu', '俞': 'Du',
    '左': 'Tả', '柳': 'Liễu', '甘': 'Cam', '祝': 'Chúc', '包': 'Bao', '宁': 'Ninh', '尚': 'Thượng',
    '符': 'Phù', '舒': 'Thư', '阮': 'Nguyễn', '柯': 'Kha', '纪': 'Kỷ', '梅': 'Mai', '童': 'Đồng',
    '凌': 'Lăng', '毕': 'Tất', '单': 'Thiện', '季': 'Quý', '裴': 'Bùi', '霍': 'Hoắc', '涂': 'Đồ',
    '成': 'Thành', '苗': 'Miêu', '谷': 'Cốc', '盛': 'Thịnh', '曲': 'Khúc', '翁': 'Ông', '冉': 'Nhiễm',
    '骆': 'Lạc', '蓝': 'Lam', '路': 'Lộ', '游': 'Du', '辛': 'Tân', '靳': 'Cận', '管': 'Quản',
    '柴': 'Sài', '蒙': 'Mông', '鲍': 'Bào', '华': 'Hoa', '喻': 'Dụ', '祁': 'Kỳ', '蒲': 'Bồ',
    '房': 'Phòng', '滕': 'Đằng', '屈': 'Khuất', '饶': 'Nhiêu', '解': 'Giải', '牟': 'Mâu', '艾': 'Ngải',
    '尤': 'Vưu', '阳': 'Dương', '时': 'Thời', '穆': 'Mục', '农': 'Nông', '司': 'Tư', '卓': 'Trác',
    '古': 'Cổ', '吉': 'Cát', '缪': 'Mâu', '简': 'Giản', '车': 'Xa', '项': 'Hạng', '连': 'Liên',
    '芦': 'Lô', '麦': 'Mạch', '褚': 'Chử', '娄': 'Lâu', '窦': 'Đậu', '戚': 'Thích', '岑': 'Sầm',
    '景': 'Cảnh', '党': 'Đảng', '宫': 'Cung', '费': 'Phí', '卜': 'Bốc', '冷': 'Lãnh', '晏': 'Yến',
    '席': 'Tịch', '卫': 'Vệ', '米': 'Mễ', '柏': 'Bách', '宗': 'Tông', '瞿': 'Cù', '桂': 'Quế',
    '全': 'Toàn', '佟': 'Đồng', '应': 'Ứng', '臧': 'Tang', '闵': 'Mẫn', '苟': 'Cẩu', '邬': 'Ổ',
    '边': 'Biên', '卞': 'Biện', '姬': 'Cơ', '师': 'Sư', '和': 'Hòa', '仇': 'Cừu', '栾': 'Loan',
    '隋': 'Tùy', '商': 'Thương', '刁': 'Điêu', '沙': 'Sa', '荣': 'Vinh', '巫': 'Vu', '寇': 'Khấu',
    '桑': 'Tang', '郎': 'Lang', '甄': 'Chân', '丛': 'Tùng', '仲': 'Trọng', '虞': 'Ngu', '敖': 'Ngao',
    '巩': 'Củng', '明': 'Minh', '佘': 'Xa', '池': 'Trì', '查': 'Tra', '麻': 'Ma', '苑': 'Uyển',
    '迟': 'Trì', '邝': 'Quảng', '官': 'Quan', '封': 'Phong', '谈': 'Đàm', '匡': 'Khuông', '鞠': 'Cúc',
    '惠': 'Huệ', '荆': 'Kinh', '乐': 'Nhạc', '冀': 'Ký', '郁': 'Úc', '胥': 'Tư', '南': 'Nam',
    '班': 'Ban', '储': 'Trữ', '原': 'Nguyên', '栗': 'Lật', '燕': 'Yến', '楚': 'Sở', '鄢': 'Yên',
    '劳': 'Lao', '谌': 'Thầm', '奚': 'Hề', '皮': 'Bì', '粟': 'Túc', '冼': 'Tiển', '蔺': 'Lận',
    '楼': 'Lâu', '盘': 'Bàn', '满': 'Mãn', '闻': 'Văn', '位': 'Vị', '厉': 'Lệ', '伊': 'Y', '仝': 'Đồng',
    '区': 'Âu', '郜': 'Cáo', '海': 'Hải', '阚': 'Hám', '花': 'Hoa', '权': 'Quyền', '强': 'Cường',
    '帅': 'Soái', '屠': 'Đồ', '豆': 'Đậu', '朴': 'Phác', '盖': 'Cái', '练': 'Luyện', '廉': 'Liêm',
    '禹': 'Vũ', '井': 'Tỉnh', '祖': 'Tổ', '漆': 'Tất', '巴': 'Ba', '丰': 'Phong', '支': 'Chi',
    '卿': 'Khanh', '国': 'Quốc', '狄': 'Địch', '平': 'Bình', '计': 'Kế', '索': 'Sách', '宣': 'Tuyên',
    '晋': 'Tấn', '相': 'Tương', '初': 'Sơ', '门': 'Môn', '云': 'Vân', '容': 'Dung', '敬': 'Kính',
    '来': 'Lai', '扈': 'Hỗ', '晁': 'Tiều', '芮': 'Nhuế', '都': 'Đô', '普': 'Phổ', '阙': 'Khuyết',
    '浦': 'Phổ', '戈': 'Qua', '伏': 'Phục', '鹿': 'Lộc', '薄': 'Bạc', '邸': 'Để', '雍': 'Ung',
    '辜': 'Cô', '羊': 'Dương', '阿': 'A', '乌': 'Ô', '母': 'Mẫu', '裘': 'Cừu', '亓': 'Kỳ', '修': 'Tu',
    '邰': 'Thai', '赫': 'Hách', '杭': 'Hàng', '况': 'Huống', '那': 'Na', '宿': 'Túc', '鲜': 'Tiên',
    '印': 'Ấn', '逯': 'Lục', '隆': 'Long', '茹': 'Như', '诸': 'Chư', '战': 'Chiến', '慕': 'Mộ',
    '危': 'Nguy', '玉': 'Ngọc', '银': 'Ngân', '亢': 'Kháng', '嵇': 'Kê', '公': 'Công', '哈': 'Cáp',
}

# Characters common in given names. Kept to readings with a single dominant Hán-Việt form.
GIVEN = {
    '一': 'Nhất', '二': 'Nhị', '三': 'Tam', '四': 'Tứ', '五': 'Ngũ', '六': 'Lục', '七': 'Thất', '八': 'Bát',
    '九': 'Cửu', '十': 'Thập', '百': 'Bách', '千': 'Thiên', '万': 'Vạn', '大': 'Đại', '小': 'Tiểu',
    '子': 'Tử', '儿': 'Nhi', '心': 'Tâm', '天': 'Thiên', '月': 'Nguyệt', '星': 'Tinh', '云': 'Vân',
    '雨': 'Vũ', '雪': 'Tuyết', '霜': 'Sương', '冰': 'Băng', '风': 'Phong', '雷': 'Lôi', '电': 'Điện',
    '春': 'Xuân', '夏': 'Hạ', '秋': 'Thu', '冬': 'Đông', '东': 'Đông', '西': 'Tây', '南': 'Nam',
    '北': 'Bắc', '中': 'Trung', '山': 'Sơn', '川': 'Xuyên', '江': 'Giang', '河': 'Hà', '湖': 'Hồ',
    '海': 'Hải', '波': 'Ba', '涛': 'Đào', '洋': 'Dương', '清': 'Thanh', '青': 'Thanh', '白': 'Bạch',
    '红': 'Hồng', '紫': 'Tử', '蓝': 'Lam', '金': 'Kim', '银': 'Ngân', '玉': 'Ngọc', '珠': 'Châu',
    '宝': 'Bảo', '贵': 'Quý', '富': 'Phú', '荣': 'Vinh', '华': 'Hoa', '福': 'Phúc', '禄': 'Lộc',
    '寿': 'Thọ', '喜': 'Hỷ', '德': 'Đức', '仁': 'Nhân', '义': 'Nghĩa', '礼': 'Lễ', '智': 'Trí',
    '信': 'Tín', '孝': 'Hiếu', '忠': 'Trung', '诚': 'Thành', '成': 'Thành', '功': 'Công', '胜': 'Thắng',
    '利': 'Lợi', '达': 'Đạt', '通': 'Thông', '光': 'Quang', '明': 'Minh', '亮': 'Lượng', '辉': 'Huy',
    '晖': 'Huy', '阳': 'Dương', '晨': 'Thần', '晓': 'Hiểu', '曦': 'Hy', '熙': 'Hy', '希': 'Hy',
    '永': 'Vĩnh', '长': 'Trường', '新': 'Tân', '正': 'Chính', '方': 'Phương', '平': 'Bình', '安': 'An',
    '宁': 'Ninh', '静': 'Tĩnh', '康': 'Khang', '健': 'Kiện', '强': 'Cường', '刚': 'Cương', '勇': 'Dũng',
    '军': 'Quân', '兵': 'Binh', '武': 'Vũ', '威': 'Uy', '毅': 'Nghị', '杰': 'Kiệt', '俊': 'Tuấn',
    '豪': 'Hào', '英': 'Anh', '雄': 'Hùng', '伟': 'Vĩ', '宏': 'Hoành', '鸿': 'Hồng', '鹏': 'Bằng',
    '飞': 'Phi', '翔': 'Tường', '龙': 'Long', '凤': 'Phượng', '虎': 'Hổ', '彪': 'Bưu', '鹰': 'Ưng',
    '峰': 'Phong', '磊': 'Lỗi', '石': 'Thạch', '林': 'Lâm', '森': 'Sâm', '木': 'Mộc', '松': 'Tùng',
    '柏': 'Bách', '竹': 'Trúc', '梅': 'Mai', '兰': 'Lan', '菊': 'Cúc', '莲': 'Liên', '荷': 'Hà',
    '花': 'Hoa', '芳': 'Phương', '芬': 'Phân', '香': 'Hương', '馨': 'Hinh', '草': 'Thảo', '叶': 'Diệp',
    '桃': 'Đào', '杏': 'Hạnh', '柳': 'Liễu', '杨': 'Dương', '楠': 'Nam', '桐': 'Đồng', '梓': 'Tử',
    '萱': 'Huyên', '薇': 'Vi', '蕾': 'Lôi', '蓉': 'Dung', '菲': 'Phi', '茜': 'Thiến', '倩': 'Thiến',
    '娟': 'Quyên', '娜': 'Na', '婷': 'Đình', '婉': 'Uyển', '媛': 'Viện', '妍': 'Nghiên', '姗': 'San',
    '珊': 'San', '琳': 'Lâm', '琪': 'Kỳ', '琦': 'Kỳ', '瑶': 'Dao', '瑜': 'Du', '璐': 'Lộ', '露': 'Lộ',
    '琴': 'Cầm', '诗': 'Thi', '雅': 'Nhã', '丽': 'Lệ', '美': 'Mỹ', '艳': 'Diễm', '秀': 'Tú', '慧': 'Tuệ',
    '惠': 'Huệ', '敏': 'Mẫn', '颖': 'Dĩnh', '欣': 'Hân', '怡': 'Di', '悦': 'Duyệt', '乐': 'Lạc',
    '爱': 'Ái', '恩': 'Ân', '思': 'Tư', '念': 'Niệm', '梦': 'Mộng', '甜': 'Điềm', '蜜': 'Mật',
    '霞': 'Hà', '燕': 'Yến', '凌': 'Lăng', '玲': 'Linh', '灵': 'Linh', '铃': 'Linh', '晶': 'Tinh',
    '婧': 'Tịnh', '娇': 'Kiều', '佳': 'Giai', '嘉': 'Gia', '可': 'Khả', '依': 'Y',
    '伊': 'Y', '涵': 'Hàm', '晗': 'Hàm', '轩': 'Hiên', '宸': 'Thần', '宇': 'Vũ', '浩': 'Hạo',
    '皓': 'Hạo', '昊': 'Hạo', '泽': 'Trạch', '然': 'Nhiên', '哲': 'Triết', '睿': 'Duệ', '航': 'Hàng',
    '铭': 'Minh', '远': 'Viễn', '帆': 'Phàm', '博': 'Bác', '文': 'Văn', '武': 'Vũ', '斌': 'Bân',
    '彬': 'Bân', '志': 'Chí', '国': 'Quốc', '建': 'Kiến', '民': 'Dân', '生': 'Sinh', '海': 'Hải',
    '军': 'Quân', '涛': 'Đào', '超': 'Siêu', '凯': 'Khải', '鑫': 'Hâm', '淑': 'Thục', '贤': 'Hiền',
    '芝': 'Chi', '兴': 'Hưng', '旺': 'Vượng', '盛': 'Thịnh', '昌': 'Xương', '隆': 'Long', '振': 'Chấn',
    '震': 'Chấn', '霖': 'Lâm', '润': 'Nhuận', '泉': 'Tuyền', '溪': 'Khê', '源': 'Nguyên', '冉': 'Nhiễm',
    '若': 'Nhược', '如': 'Như', '晴': 'Tình', '彤': 'Đồng', '丹': 'Đan', '朵': 'Đóa', '容': 'Dung',
    '颜': 'Nhan', '雯': 'Văn', '倍': 'Bội', '蓓': 'Bội', '妮': 'Ni', '娅': 'Á', '亚': 'Á', '莉': 'Lỵ',
    '莎': 'Sa', '琼': 'Quỳnh', '瑞': 'Thụy', '祥': 'Tường', '吉': 'Cát', '庆': 'Khánh', '欢': 'Hoan',
    '桂': 'Quế', '月': 'Nguyệt', '宁': 'Ninh', '媚': 'Mị', '婕': 'Tiệp', '蕊': 'Nhụy', '岚': 'Lam',
    '雁': 'Nhạn', '鹤': 'Hạc', '鸣': 'Minh', '声': 'Thanh', '音': 'Âm', '韵': 'Vận', '琛': 'Sâm',
    '璇': 'Toàn', '翠': 'Thúy', '黛': 'Đại', '嫣': 'Yên', '婵': 'Thiền', '娥': 'Nga', '珍': 'Trân',
    '宝': 'Bảo', '启': 'Khải', '明': 'Minh', '东': 'Đông', '旭': 'Húc', '昕': 'Hân', '昭': 'Chiêu',
    '景': 'Cảnh', '致': 'Trí', '远': 'Viễn', '德': 'Đức', '秋': 'Thu', '义': 'Nghĩa', '良': 'Lương',
    '善': 'Thiện', '友': 'Hữu', '朋': 'Bằng', '松': 'Tùng', '彦': 'Ngạn', '奇': 'Kỳ', '琼': 'Quỳnh',
    '泰': 'Thái', '贝': 'Bối', '妙': 'Diệu', '蝶': 'Điệp', '琬': 'Uyển', '纯': 'Thuần', '洁': 'Khiết',
    '素': 'Tố', '真': 'Chân', '贞': 'Trinh', '淼': 'Miểu', '飘': 'Phiêu', '逸': 'Dật', '轶': 'Dật',
    '祺': 'Kỳ', '麒': 'Kỳ', '麟': 'Lân', '璋': 'Chương', '章': 'Chương', '岩': 'Nham', '坤': 'Khôn',
    '乾': 'Càn', '钧': 'Quân', '铮': 'Tranh', '锋': 'Phong', '剑': 'Kiếm', '刀': 'Đao', '枫': 'Phong',
    '桦': 'Hoa', '榕': 'Dung', '樱': 'Anh', '槿': 'Cận', '茵': 'Nhân', '苒': 'Nhiễm', '芸': 'Vân',
    '蕴': 'Uẩn', '蔚': 'Úy', '璟': 'Cảnh', '珏': 'Giác', '瑾': 'Cẩn', '瑛': 'Anh', '琰': 'Diễm',
}

# Surnames that also start ordinary words (那天, 和他, 高兴, 时间 ...). Frequency alone
# is not evidence for these; they are accepted only when jieba tags the word as a name.
AMBIGUOUS = set('于方白金石江万华龙宁向常明和时来都那全门相初平国花海高成安文云容敬普阿乌母宿鲜印公哈'
                '战危玉银南原满闻位区权强帅豆盖练井祖巴丰支计索宣伏鹿薄羊修况隆诸慕路车关包管应解单师连'
                '麦景党宫费卜冷席卫米柏宗边商沙荣桑郎池查麻官封谈惠乐班储燕楚劳皮楼盘伊屠朴漆卿晋戈茹亢'
                '申兰左甘尚符童凌毕季谷盛曲蓝游辛蒙房艾尤阳农司古吉简项易齐乔安习')


def reading(name):
    """Hán-Việt for a full name, or None when any character is uncertain."""
    for compound, value in COMPOUND_SURNAMES.items():
        if name.startswith(compound) and len(name) > len(compound):
            given = [GIVEN.get(ch) for ch in name[len(compound):]]
            return None if None in given else ' '.join([value, *given])
    if name[0] not in SURNAMES or len(name) < 2:
        return None
    given = [GIVEN.get(ch) for ch in name[1:]]
    return None if None in given else ' '.join([SURNAMES[name[0]], *given])


def given_reading(given):
    parts = [GIVEN.get(ch) for ch in given]
    return None if None in parts else ' '.join(parts)


def detect(rows, minimum=3, limit=40):
    """Glossary entries [{source, target, count, auto}] for frequent person names."""
    import jieba
    import jieba.posseg
    jieba.setLogLevel(60)
    text = '\n'.join(rows)
    tags = jieba.posseg.dt.word_tag_tab

    def is_word(gram):
        # A dictionary word that is not tagged as a person name (张开, 高兴, 金钱 ...).
        return gram in tags and not tags[gram].startswith('nr')

    tagged = Counter(word for row in rows for word, flag in jieba.posseg.cut(row)
                     if flag == 'nr' and 2 <= len(word) <= 4)
    grams = Counter()
    for size in (2, 3, 4):
        for start in range(len(text) - size + 1):
            gram = text[start:start + size]
            if '\n' not in gram and (gram[0] in SURNAMES or gram[:2] in COMPOUND_SURNAMES):
                grams[gram] += 1
    candidates = {}
    for gram, count in grams.items():
        if count < minimum or is_word(gram) or reading(gram) is None:
            continue
        if gram[:2] not in COMPOUND_SURNAMES and (len(gram) == 4 or gram[0] in AMBIGUOUS):
            continue  # rarely a name / needs the jieba name tag below
        candidates[gram] = count
    for word, count in tagged.items():
        if reading(word) and grams[word] >= 2:
            candidates[word] = max(candidates.get(word, 0), grams[word])
    # Prefer the longest form: drop 张倩 when 张倩倩 accounts for nearly all its uses.
    for gram in sorted(candidates, key=len):
        longer = [g for g in candidates if len(g) > len(gram) and g.startswith(gram)]
        if longer and grams[gram] - sum(grams[g] for g in longer) < minimum:
            candidates.pop(gram, None)
    # A 3-character gram dominated by its 2-character prefix is the name plus a word (李强家).
    for gram in [g for g in candidates if len(g) == 3 and g[:2] in candidates]:
        if grams[gram[:2]] >= 4 * grams[gram]:
            candidates.pop(gram)
    # Drop a shorter candidate that only appears inside longer ones (倩倩 inside 张倩倩 is kept
    # as an alias below when it also stands alone).
    names = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))[:limit]
    entries = [dict(source=name, target=reading(name), count=count, auto=True) for name, count in names]
    # Given-name aliases (倩倩 for 张倩倩) when they also occur without the surname.
    for name, _ in names:
        surname = 2 if name[:2] in COMPOUND_SURNAMES else 1
        given = name[surname:]
        alone = text.count(given) - text.count(name)
        if len(given) >= 2 and alone >= 2 and not is_word(given) and given_reading(given):
            if all(entry['source'] != given for entry in entries):
                entries.append(dict(source=given, target=given_reading(given), count=alone, auto=True))
    return sorted(entries, key=lambda entry: (-len(entry['source']), -entry['count']))
