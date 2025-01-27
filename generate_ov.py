from chatglm2.modeling import ChatGLMModel
from qwen.modeling import QwenModel
from baichuan2.modeling import BaichuanModel
from internlm.modeling import InternLMModel
import argparse
import time
from utils import process_response

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-h',
                        '--help',
                        action='help',
                        help='Show this help message and exit.')
    parser.add_argument('-m',
                        '--model_path',
                        required=True,
                        type=str,
                        help='Required. model path')
    parser.add_argument('-p',
                        '--prompt',
                        default="请介绍一下上海？",
                        required=False,
                        type=str,
                        help='Required. prompt sentence')
    parser.add_argument('-l',
                        '--max_sequence_length',
                        default=128,
                        required=False,
                        type=int,
                        help='Required. maximun lengh of output')
    parser.add_argument('-d',
                        '--device',
                        default='CPU',
                        required=False,
                        type=str,
                        help='Required. device for inference')
    args = parser.parse_args()

    model_id = args.model_path
    if 'chatglm2' in model_id:
        ov_model = ChatGLMModel(model_id, args.device)
    elif 'qwen' in model_id:
        ov_model = QwenModel(model_id, args.device)
    elif 'baichuan2' in model_id:
        ov_model = BaichuanModel(model_id, args.device)
    elif 'internlm' in model_id:
        ov_model = InternLMModel(model_id, args.device)
    else:
        raise NotImplementedError(f"Unsupported model id {model_id!r}")
    
    input_data = ov_model.build_inputs([], args.prompt)
    print(" --- start generating --- ")
    start = time.perf_counter()
    response, num_tokens = ov_model.generate_sequence(
        input_data, max_generated_tokens=args.max_sequence_length)
    end = time.perf_counter()
    answer = process_response(
        ov_model.tokenizer.decode(response, skip_special_tokens=True))
    answer = answer.split("<eoa>")[0]
    print(answer)
    print(f"Generated {num_tokens} tokens in {end - start:.3f} s")