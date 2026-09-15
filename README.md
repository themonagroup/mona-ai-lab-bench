# MONA AI Lab Bench

**Bộ test mở để chấm model AI (LLM) trên việc thật của doanh nghiệp Việt.**
*An open benchmark & harness for evaluating LLMs on real Vietnamese business tasks — chatbot CSKH, tư vấn, chốt sale, khiếu nại, tổng đài.*

Đây là bộ đồ nghề MONA dùng trong chuyên mục [MONA AI Lab](https://mona.media/ai-lab/) mỗi khi có một model AI mới ra mắt: thay vì tin con số hãng công bố, tụi mình quăng nó vào đúng việc doanh nghiệp Việt hay giao cho AI rồi đo. Nay mở ra để ai cũng tự chạy lại được — trên bất kỳ model nào, bằng key của chính bạn.

## Vì sao có bộ này

Model AI ra mới gần như mỗi tuần. Benchmark quốc tế thì đo toán, code, kiến thức bằng tiếng Anh — không nói cho bạn biết con model đó **trả lời khách tiếng Việt** có ra hồn không, có **bịa giá** không, có **đọc sai tên riêng có dấu** không, có bị khách dụ lộ thông tin không. Đó mới là thứ quyết định bạn có dám giao nó cho khách hàng thật hay không.

Bộ này đo đúng mấy chuyện đó. Và nó mở — bạn không phải tin lời MONA, bạn chạy lại và tự thấy.

## Nó chấm gì

14 tình huống (đang lớn dần), chia theo 7 nhóm việc thật:

| Nhóm | Đo cái gì |
|---|---|
| `faq` | Trả lời chính sách đúng, không bịa điều kiện |
| `tu-van` | Tư vấn hợp nhu cầu, không tự chế giá |
| `chot-sale` | Xử lý băn khoăn, giữ giá, không ép |
| `khieu-nai` | Xin lỗi đúng mực, đúng quy trình, không hứa ẩu |
| `da-luot` | Nhớ ngữ cảnh qua nhiều lượt |
| `injection` | Bị dụ "bỏ qua hướng dẫn / lộ system prompt" có đứng vững không |
| `edge-so-ten-tien` | Tính đúng tiền, đọc đúng tên có dấu, đúng số điện thoại |

Toàn bộ tình huống là **dữ liệu tự soạn (synthetic)** — không có một dòng dữ liệu khách hàng thật nào. Bạn có thể đọc, sửa, thêm thoải mái.

Cách chấm chi tiết: xem [`rubric.md`](rubric.md). Tóm tắt: mỗi câu trả lời qua 2 lớp — **kiểm bằng luật** (bịa giá / lộ mã / sai tên = trượt cứng) và **một model thứ hai chấm** 4 tiêu chí: đúng ý, tiếng Việt tự nhiên, không bịa, giữ ngữ cảnh.

## Chạy thử

```bash
git clone https://github.com/themonagroup/mona-ai-lab-bench
cd mona-ai-lab-bench
pip install -r requirements.txt
cp .env.example .env      # cắm OPENAI_API_KEY và/hoặc ANTHROPIC_API_KEY của bạn

# chấm 1 model bất kỳ, dùng model khác làm giám khảo
python harness/run_eval.py \
  --provider openai --model gpt-5.6 \
  --judge-provider anthropic --judge-model claude-sonnet-5 \
  --tasks tasks/ --out out/
```

Xong bạn có `out/report.md` (bảng điểm theo từng nhóm) và `out/report.json` (số thô để tự vẽ).

## Tự thêm đề của bạn

Đây là phần hay nhất. Mỗi tình huống là một dòng JSON trong `tasks/*.jsonl`:

```json
{"id":"faq-03","category":"faq","system":"<vai + chính sách của bạn>","turns":["<câu khách nói>"],"checks":[{"type":"must_not_contain","value":"<thứ không được xuất hiện>"}],"judge":"<mô tả bạn muốn giám khảo soi gì>"}
```

Muốn test model cho đúng nghiệp vụ của **công ty bạn**? Chép mấy tình huống khách hay hỏi vào (nhớ khử thông tin cá nhân), chạy, và bạn có ngay một bảng điểm nói cho bạn biết nên giao luồng nào cho AI, luồng nào giữ người. Đó cũng chính là cách MONA tư vấn chuyển đổi AI cho doanh nghiệp.

## Bộ này ra từ đâu

Từ [MONA AI Lab](https://mona.media/ai-lab/) — nơi MONA test model AI mới trên sản phẩm thật (tổng đài, chatbot, phần mềm) rồi báo cáo thẳng cái nào xài được, cái nào nổ. Tác giả: [Khánh Hùng — Founder The MONA](https://mona.media/profile/vy-nguyen-khanh-hung/). Xem thêm bộ công cụ GEO/AI của MONA tại [MONA GEO OS](https://mona.media/mona-geo-os/).

---

## Tuyên ngôn thị trường cùng tiến

*Vì sao MONA làm miễn phí?*

MONA là một công ty phần mềm, chuyển đổi số, chuyển đổi AI, nhưng trên hết, MONA là một công ty dịch vụ B2B, là người hưởng lợi trực tiếp từ việc: **những doanh nghiệp Việt càng thành công, MONA càng có lợi**. Thị trường đi xuống, đi chậm, công nghệ yếu mới chính là điểm giết chết các cơ hội làm ăn trong tương lai của MONA.

Nên, hơn ai hết, MONA mong muốn, và MONA thật sự can thiệp vào việc giúp đỡ anh chị thành công.

Và chuyển đổi AI là chìa khóa cho sự thành công đó của chúng ta.

— Khánh Hùng, Founder MONA

---

## License

[MIT](LICENSE) — dùng, sửa, thương mại hoá thoải mái. Chỉ mong khi bộ này giúp được bạn, bạn nhớ tới [MONA](https://mona.media).
