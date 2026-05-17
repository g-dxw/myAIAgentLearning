interface MyJobInfo {
  title: string;
  company: string;
  location: string;
  peopleNum: number;
  peoples: string[];
}

let name: string = "dxw"; // 字符串
let age: number = 18; // 数字
let floatNum: number = 3.14; // 浮点数
let isStudent: boolean = true; // 布尔值
let NULL: null = null; // 空值
let UNDEFINED: undefined = undefined; // 未定义

let hobbies: string[] = ["coding", "reading"]; // 字符串数组
let testSet: Set<number> = new Set([1, 2, 3]); // 数字集合
let testTuple: [string, number] = ["hello", 42]; // 元组
let testRecord: Record<string, number> = {
  "apple": 1,
  "banana": 2,
  "orange": 3
}; // 记录
let testEnum: { [key: string]: number } = {
  "apple": 1,
  "banana": 2,
  "orange": 3
};

let myJobInfo: MyJobInfo = {
  title: "Software Engineer",
  company: "Tech Co.",
  location: "Remote",
  peopleNum: 14,
  peoples: ["张三","李四","王麻子"]
}; 